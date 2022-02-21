#!google-api-python-client/bin/python2.7

from __future__ import print_function

import httplib2, os, datetime, json, logging, logging.config
from apiclient import discovery
from flask import Flask, abort, request, json, jsonify
from oauth2client import client, tools
from oauth2client.file import Storage
from oauth2client.service_account import ServiceAccountCredentials

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

def setup_logging(
    default_path='logging.json',
    default_level=logging.INFO,
    env_key='LOG_CFG'
):
    # Setup logging configuration
    path = default_path
    value = os.getenv(env_key, None)
    if value:
        path = value
    if os.path.exists(path):
        with open(path, 'rt') as f:
            config = json.load(f)
        logging.config.dictConfig(config)
    else:
        logging.basicConfig(level=default_level)

setup_logging()
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']
CLIENT_SECRET_FILE = 'client_secret_107325843719441357488.json'
APPLICATION_NAME = 'Change Calendar Integration'
NORMAL_CHANGE_CALENDAR = 'redhat.com_flloc373g7dvltedrnc2q8erp4@group.calendar.google.com'
STANDARD_CHANGE_CALENDAR = 'redhat.com_u1d7ht60gsaa9aes7f0l1lr2fg@group.calendar.google.com'
URGENT_CHANGE_CALENDAR = 'redhat.com_s5f0olmmh9loftt04vvm80r7qg@group.calendar.google.com'
UNAPPROVED_CHANGE_CALENDAR = 'redhat.com_m06jujv2or2p1ut5gjp3mnno5s@group.calendar.google.com'
LATENT_CHANGE_CALENDAR = 'redhat.com_7in87m4t0tnq5msq9b4mut5v2k@group.calendar.google.com'
FAILED_CHANGE_CALENDAR = 'redhat.com_0pnmo0ovttjt27d27s4vvh6fng@group.calendar.google.com'

# Setup API routes

app = Flask(__name__)

def get_credentials():
    # Gets valid service account credentials from storage.

    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        'snow-calendar-updates-94c48f75811c.json', SCOPES
    )
    
    return credentials

CREDENTIALS = get_credentials()


def getChangeCalendar(approval, state, type):
    if approval == 'requested':
        return UNAPPROVED_CHANGE_CALENDAR

    if state == 9 or state == 4:
        return FAILED_CHANGE_CALENDAR
    
    elif type == 'Comprehensive':
        return NORMAL_CHANGE_CALENDAR

    elif type == 'Routine':
        return STANDARD_CHANGE_CALENDAR

    elif type == 'Expedited' or type == 'Emergency':
        return URGENT_CHANGE_CALENDAR

    elif type == 'Latent':
        return LATENT_CHANGE_CALENDAR

    else:
        return NORMAL_CHANGE_CALENDAR

def getEventColor(type):
    return '0' # Calendar sets color

'''
    # Event colors based on risk

    if risk == '4': # Low -> Light blue
        return '1'

    elif risk == '3': # Medium - > Yellow
        return '5'

    elif risk == '2' or risk == '1': # High, Very High -> Red
        return '11'

    else:
        return '1'
'''

def getAttendees(r):
    attendees = []

    # Required attendees
    if r['assigneeID'] == r['requestedByID']:
        attendees.append( {'email': r['assigneeID']} )
    
    else: 
        attendees.append( {'email': r['requestedByID']} )
        attendees.append( {'email': r['assigneeID']} )

    # Optional attendees
    if r['watchList']:
        for email in r['watchList']:
            attendees.append( {'email': email, 'optional': True} )

    return attendees


def getCalendarEvent(service, calendarID, eventID):
    
    # Get event
    eventResult = service.events().get(
        calendarId=calendarID, eventId=eventID
    ).execute()

    logger.info('Get event: '+eventResult['id']+' from '+calendarID)

    return eventResult


def getCalendarService(userID, r):
    
    # Impersonate calendar owner
    delegated_credentials = CREDENTIALS.create_delegated(userID)
    service = discovery.build('calendar', 'v3', credentials=delegated_credentials, cache_discovery=False)

    logger.info('Get service for: '+userID)

    # Build API access and check if created by jhamann (previous owner)
    if 'calendarID' in r and 'eventID' in r:
        event = getCalendarEvent(service, r['calendarID'], r['eventID'])
        creator = event['creator']
        
        if creator['email'] == 'jhamann@redhat.com':
            delegated_credentials = CREDENTIALS.create_delegated('jhamann@redhat.com')
            logger.info('Overriding credentials to use jhamann -- workaround creator permissions issue')
            service = discovery.build('calendar', 'v3', credentials=delegated_credentials, cache_discovery=False)
    
    return service
    

def moveChangeEvent(service, oldCalendarId, newCalendarId, eventId):
    eventResult = service.events().move(
        calendarId=oldCalendarId, eventId=eventId, destination=newCalendarId
    ).execute()

    logger.info('Moved event: '+eventResult['id']+' from '+oldCalendarId+' to '+newCalendarId)


# Setup API routes

app = Flask(__name__)

@app.route('/gcal/api/v1/delete-change-event', methods=['POST'])
def deleteChangeEvent():
    
    r = request.get_json()  
    if not r or not 'ownerID' in r or not 'eventID' in r:
        abort(400)
    
    service = getCalendarService(r['ownerID'], r)

    eventBody = {
        'start': {'dateTime': r['start'], 'timeZone': r['tz']},
        'end': {'dateTime': r['end'], 'timeZone': r['tz']},
        'status': 'cancelled'
    }
    
    eventResult = service.events().update(
        calendarId=r['calendarID'], eventId=r['eventID'], body=eventBody
    ).execute()
    
    logger.info('Deleted event: '+r['eventID'])
    return jsonify( {'eventID': r['eventID']} )


@app.route('/gcal/api/v1/update-change-event', methods=['POST'])
def updateChangeEvent():

    r = request.get_json()
    if not r or not 'ownerID' in r or not 'assigneeID' in r or not 'changeType' in r or not 'changeID' in r:
        abort(400)
    
    service = getCalendarService(r['ownerID'], r)

    # Now time as reference for demo
    #now = datetime.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time

    calendar = getChangeCalendar(r['approval'], r['state'], r['changeType'])
    
    if 'eventID' in r and calendar != r['calendarID']:
        moveChangeEvent(service, r['calendarID'], calendar, r['eventID'])

    eventBody = {
        'creator': {'email': r['requestedByID']},
        'organizer': {'email': r['requestedByID']},
        'attendees': getAttendees(r),
        'start': {'dateTime': r['start'], 'timeZone': r['tz']},
        'end': {'dateTime': r['end'], 'timeZone': r['tz']},
        'location': r['locations'] if 'locations' in r else '',
        'summary': r['changeID']+': '+r['shortDescription'],
        'description': r['description'],
        'status': r['status'],
        'colorId': getEventColor(r['risk']),
        'locked': True,
        'source': {
            'title': r['changeID']+': '+r['shortDescription'],
            'url': r['sourceUrl']
        }
    }

    # Try to update existing event
    if 'eventID' in r:
        logger.info('Updating existing change event: '+r['eventID']+' based on '+r['changeID'])
        eventResult = service.events().update(
            calendarId=calendar, eventId=r['eventID'], body=eventBody
        ).execute()

        logger.info('Updated event: '+eventResult['id'])
        return jsonify( {'eventID': eventResult['id'], 'calendarID': calendar} )
    
    # Try to create new event
    else:
        logger.info('Adding change event based on '+r['changeID'])
        eventResult = service.events().insert(
            calendarId=calendar, body=eventBody
        ).execute()

        logger.info('Created event: '+eventResult['id'])
        return jsonify( {'eventID': eventResult['id'], 'calendarID': calendar} )

if __name__ == '__main__':
    app.run(port=5005, debug=False, use_reloader=False)
