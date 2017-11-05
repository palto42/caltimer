#!/usr/bin/python3

# #######################################################
# Calernder based scheduler to switch RF433 sockets     #
# using cli codesend or direct GPIO                     #
#                                                       #
# Extra options can be defined in the description       #
# filed of each event, using an ini-style format:       #
#   [random]                                            #
#   # add random offset for start/end time              #
#   # values can be positive or negative                #
#   # "all" option is applied to start and end          #
#   start : max random time in minutes                  #
#   end : max random time in minutes                    #
#   all : max random time in minutes                    #
#                                                       #
#   [sun]                                               #
#   # replace the start/end time with the current       #
#   # sunrise or sunset time +/- offset                 #
#   start : rise or set                                 #
#   end : rise or set                                   #
#   start_offset : offset in minutes                    #
#   end_offset : offset in minutes                      #
#                                                       #
# Matthias Homann                                       #
# 2017-11-05                                            #
# #######################################################


import logging
import sys
import configparser
import subprocess
import sched
import time
from datetime import datetime, date, timedelta
from random import uniform
import caldav
# from caldav.elements import dav, cdav
from sunrise_sunset import SunriseSunset
import RPi.GPIO as GPIO
from rpi_rf import RFDevice
import argparse

# set initial logging to stderr, level INFO
logging.basicConfig(
    stream=sys.stderr,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    level=logging.INFO)


def rf_switch(switch, onoff, stime):
    if onoff:
        sendcode = config[switch]['oncode']
    else:
        sendcode = config[switch]['offcode']
    logging.info('<<< rf_switch schedule to send RF code %s at time %s via %s',
                 sendcode,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        s.enterabs(stime, 1, subprocess.call,
                   argument=([config['DEFAULT']['rf433'], sendcode,
                              config[switch]['protocol'],
                              config[switch]['pulselength']],))
    elif config[switch]['rf_code'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code, argument=(
            int(sendcode), int(config[switch]['protocol']),
            int(config[switch]['pulselength'])))
    else:
        logging.error(
            'rf_switch undefined rf_code for switch %s, check ini file!',
            switch)


def rf_comag(switch, onoff, stime):
    # Comag code calculation:
    # switch 0 = binary "01"
    # switch 1 = binary "00"
    # ON  = 10 = binary "0001"
    # OFF = 01 = binary "0100"
    #
    # Example:
    # Channel   Socket    ON/OFF
    # 0 1 0 0 0 0 0 1 1 0 10/01

    # Create binary code
    bincode = config[switch]['system'] + config[switch]['receiver']
    if onoff:
        bincode += '10'
    else:
        bincode += '01'
    logging.debug('*** Comag binary code = %s', bincode)
    # translate
    sendcode = 0
    for c in bincode:
        sendcode = sendcode << 2
        if c == "0":
            sendcode = sendcode | 1
    logging.debug('*** Comag sendcode = %s', '{:08b}'.format(sendcode))
    logging.info('<<< rf_comag schedule to send RF code %s at time %s via %s',
                 sendcode,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        s.enterabs(stime, 1, subprocess.call,
                   argument=([config['DEFAULT']['rf433'],
                              str(sendcode), "1", "350"],))
    elif config[switch]['rf_code'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code,
                   argument=(int(sendcode), 1, 350))
    else:
        logging.error(
            'rf_comag undefined rf_code for switch %s, check ini file!',
            switch)


def rf_zap(switch, onoff, stime):
    # ZAP/REV code calculation:_
    # tristate
    #   0 = binary "00"
    #   1 = binary "11"
    #   F = binary "01"
    # ON  = tri 01 = binary "0011"
    # OFF = tri 10 = binary "1100"
    #
    # Example:
    # ZAP-Code   Channel (F=open)  | Key 5..1          | On=01 Off=10
    # tri-state  0   0   F   F   F | 1   F   F   0   0 | 0   1
    # binary     00  00  01  01  01| 11  01  01  00  00| 00  11
    #            = 000001010111010100000011

    # The ZAP switch config provides:
    # 'channel'  : tri-state
    # 'zap_base' : tri-state base for the key part
    # 'key'      : decimal number of the receiver

    # Create binary code
    sendcode = 0
    for c in config[switch]['channel']:
        sendcode = sendcode << 2
        if c == '1':
            sendcode = sendcode | 3
        elif c == 'F':
            sendcode = sendcode | 1
    key_code = list(config[switch]['zap_base'])
    key_code[5-int(config[switch]['key'])] = "1"
    for c in key_code:
        sendcode = sendcode << 2
        if c[0] == '1':
            sendcode = sendcode | 3
        elif c[0] == 'F':
            sendcode = sendcode | 1
    sendcode = sendcode << 4
    if onoff:
        sendcode = sendcode | 3
    else:
        sendcode = sendcode | 12
    logging.debug('*** ZAP sendcode = %s', '{:08b}'.format(sendcode))
    logging.info('<<< rf_zap schedule to send RF code %s at time %s via %s',
                 sendcode,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        s.enterabs(
            stime, 1, subprocess.call,
            argument=([config['DEFAULT']['rf433'],
                       str(sendcode), "1", "188"],))
    elif config[switch]['rf_code'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code, argument=(sendcode, 1, 188))
    else:
        logging.error(
            'rf_zap undefined rf_code for switch %s, check ini file!', switch)


def gpio_switch(switch, onoff, stime):
    # Set the pin to output (just to be sure...)
    try:
        GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except:
        logging.error('GPIO setup error for pin %d', config[switch]['pin'])
    # Can directly use the Boolean variable onoff since True=1=GPIO.HIGH
    s.enterabs(stime, 1, GPIO.output,
               argument=(int(config[switch]['pin']), onoff))
    logging.info('<<< Schedule GPIO %s %s at %s', config[switch]['pin'],
                 onoff, time.strftime('%H:%M:%S', time.localtime(stime)))


def gpio_pulse(switch, onoff, stime):
    # Set the pin to output (just to be sure...)
    try:
        GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except:
        logging.error('GPIO setup error for pin %d', config[switch]['pin'])
# Get the duration of the pulse
    if onoff:
        pulsetime = float(config[switch]['on'])
    else:
        pulsetime = float(config[switch]['off'])
# Check for maximum pulse length, e.g. 10s (configured in config.ini)
    if pulsetime > float(config['DEFAULT']['max_pulse']):
        logging.error(
            'The pulse duration of %s s is too long, setting to max= %s',
            pulsetime, config['DEFAULT']['max_pulse'])
        pulsetime = float(config['DEFAULT']['max_pulse'])
    logging.info(
        '<<< Schedule GPIO %s pulse %s at %s', config[switch]['pin'],
        onoff, time.strftime('%H:%M:%S', time.localtime(stime)))
    s.enterabs(stime, 1, GPIO.output, argument=(int(config[switch]['pin']), 1))
    s.enterabs(stime+pulsetime, 1, GPIO.output,
               argument=(int(config[switch]['pin']), 0))


def dummy_switch(switch, onoff, stime):
    s.enterabs(stime, 1, logging.warning,
               argument=('Dummy event action: %s', onoff))


def configure_logging(log_arg):
    loglevel = {
        'CRITICAL': 50,
        'ERROR':    40,
        'WARNING':  30,
        'INFO':     20,
        'DEBUG':    10,
        'NOTSET':    0
    }
    # check if logfile is defined and can be opened for read
    try:
        logfile = open(config['LOGGING']['logfile'], 'r')
        logfile.close()
        log_exists = True
        #-------------------------------------- print ('File exists',log_exists)
    except:
        log_exists = False
    # check if logfile is defined and can be opened for write/append
    try:
        logfile = open(config['LOGGING']['logfile'], 'a')
        logfile.close()
        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        # Reconfigure logging again, this time with a file.
        logging.basicConfig(
            filename=config['LOGGING']['logfile'],
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    except:
        if log_exists:
            temp_log = config['LOGGING']['logfile'][:-4] \
                + time.strftime("_%y-%m-%d_%H-%M")+".log"
            logging.error(
                'Logfile is already in use by other process, '
                'using temp logfile: %s',
                temp_log)
            try:  # try to open new logfile write
                logfile = open(temp_log, 'w')
                logfile.close()
                # Remove all handlers associated with the root logger object.
                for handler in logging.root.handlers[:]:
                    logging.root.removeHandler(handler)
                # Reconfigure logging again, this time with a file.
                logging.basicConfig(
                    filename=temp_log, level=logging.INFO,
                    format='%(asctime)s - %(module)s -'
                    ' %(levelname)s : %(message)s')
            except:
                logging.error(
                    'No write access for temp logfile, '
                    'using sdterr for logging.')
        else:
            logging.error('No (correct) filename defined, '
                          'using sdterr for logging.')
    # log level set as command line parameter?
    if log_arg is not None:
        try:
            logging.info('Set loglevel: %s', log_arg)
            logging.getLogger().setLevel(loglevel[log_arg.upper()])
        except:
            print ('ERROR: Incorrect loging level specified, '
                   'using log evel "ERROR"')
            logging.getLogger().setLevel(logging.ERROR)
    # if not, set logging level as defined in caltimer.ini
    else:
        logging.info('---------------------------------'
                     '---------------------------------')
        try:
            logging.info('Set loglevel: %s', config['LOGGING']['loglevel'])
            logging.getLogger().setLevel(
                loglevel[config['LOGGING']['loglevel']])
        except:
            logging.error('No loglevel defined, using ERROR')
            logging.getLogger().setLevel(logging.ERROR)


#############################################################
# MAIN                                                      #
#############################################################
def main():

    # Switch command options
    # usage: switch_type[type]()
    switch_type = {
        'rf':    rf_switch,
        'comag': rf_comag,
        'zap':   rf_zap,
        'gpio':  gpio_switch,
        'pulse': gpio_pulse,
        'dummy': dummy_switch,
        }

    # Comamnd line arguments
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-i', '--init',
                        help='specify path/filename of ini file to read from',
                        default='/etc/caltimer/caltimer.ini')
    parser.add_argument('-l', '--log',
                        help='set log level (overwrites ini file)\n'
                        '  Supported levels are: '
                        'CRITICAL, ERROR, WARNING, INFO, DEBUG')
    parser.add_argument('-t', '--time-interval',
                        help='scheduler time interval in minutes')
    parser.add_argument('-r', '--sun-rise',
                        help='manually set the sunrise time as "06:00"')
    parser.add_argument('-s', '--sun-set',
                        help='manually set the sunset time as "21:00"')
    args = parser.parse_args()

    # Read ini file for RC switch definition
    # keys: oncode, offcode, protocol, pulselength
    # example: config['switchname']['oncode']
    global config
    config = configparser.ConfigParser()
    config.sections()
    config.read(args.init)
    if len(config) <= 1:
        print ("ERROR: The specified ini file doesn't exit!")
        return

    # Raspberry Pi GPIO settings
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Enable RF transmitter
    global rfdevice
    rfdevice = RFDevice(int(config['DEFAULT']['gpio']))
    rfdevice.enable_tx()

    # Time zone offset
    tzoffset = datetime.today().hour-datetime.utcnow().hour

    # set logfile destination and log level
    configure_logging(args.log)

    # Set Caldav url
    try:
        url = config['CALENDAR']['caldav']
    except:
        logging.error('Missing or incorrect ini file,'
                      ' please check /etc/caltimer/caltimer.ini')
        return

    # Scheduler interval in minutes
    try:
        if args.time_interval is not None:
            interval = int(args.time_interval)
        else:
            interval = int(config['CALENDAR']['interval'])
    except:
        logging.error(
            'Defined scheduler time interval is not an integer number!')
        return

    # event options
    event_options = configparser.ConfigParser()

    # try to access the web calendar
    client = caldav.DAVClient(url)
    try:
        principal = client.principal()
    except:
        e = sys.exc_info()[0]
        logging.error('Error to access the web calendar: %s', e)
        return
    calendars = principal.calendars()
    if len(calendars) == 0:
        logging.error('No calender found at URL: %s', url)
        return
    else:
        # Check if specified calendar is available
        calendar = next((c for c in calendars if
                         c.name == config['CALENDAR']['calname']), None)
        if calendar is None:
            logging.error(
                'Calendar %s not found.', config['CALENDAR']['calname'])
            logging.error('Available calendars:')
            for calendar in calendars:
                logging.error('  %s ', calendar.name)
            return
        logging.info("Using calendar %s", calendar)

    # Specified calendar is available
    
    # get start and end times for next time interval
    dt = datetime.today()
    # calculate next start time after current time
    dt_start = dt + timedelta(minutes=interval - dt.minute % interval,
                        seconds=-(dt.second % 60),
                        microseconds=-(dt.microsecond % 1000000))
    dt_end = dt+timedelta(minutes=interval)

    logging.info("Get events between: %s and %s", dt_start, dt_end)
    results = calendar.date_search(
        dt_start - timedelta(hours=tzoffset),
        dt_end - timedelta(hours=tzoffset))
    logging.debug('%s events found for defined period.', len(results))

    # is below required? Seems to be set again later 
    r_time_1 = 0
    r_time_2 = 0

    if len(results) > 0:
        # calculate sunrise and sunset
        ro = SunriseSunset(
            datetime.now(), latitude=float(config['CALENDAR']['latitude']),
            longitude=float(config['CALENDAR']['longitude']),
            localOffset=float(config['CALENDAR']['local_offset']))
        rise_time, set_time = ro.calculate()
        # set sun times manually for test purposes
        if args.sun_rise is not None:
            rise_time = datetime.strptime(str(date.today())+" "+args.sun_rise,
                                          "%Y-%m-%d %H:%M")
        if args.sun_set is not None:
            temp_time = str(date.today())+" "+args.sun_set
            set_time = datetime.strptime(str(date.today())+" "+args.sun_set,
                                         "%Y-%m-%d %H:%M")

        logging.info('Sunrise %s, sunset %s', rise_time, set_time)

        # schedule events
        logging.debug('Define scheduler')
        global s
        s = sched.scheduler(time.time, time.sleep)
        for event in results:
            event.load()
            e = event.instance.vevent
            schedule_start = False
            schedule_end = False
            # check if the event has a known switch 
            # defined in the location field
            if not config.has_section(e.location.value):
                logging.error(
                    '>>> Event "%s" at %s has an undefined RF-switch "%s"'
                    ', skipping this event.',
                    e.summary.value, e.dtstart.value.strftime("%H:%M"),
                    e.location.value)
            elif not config[e.location.value]['type'] in switch_type:
                logging.error(
                    '>>> RF-switch "%s" uses undefined type "%s" , '
                    'check ini file. Skipping this event.',
                    e.location.value, config[e.location.value]['type'])
            # found known switch, get event start/stop times
            else:
                # Calculate event start/end time for current date
                # (required for recurring events)
                # TODO: possible issue if interval would span across midnight
                e_start_dt = datetime.combine(date.today(),
                                              e.dtstart.value.time())
                e_end_dt = datetime.combine(date.today(),
                                            e.dtend.value.time())
                e_start = e_start_dt.timestamp()
                e_end = e_end_dt.timestamp()

                # check if start/stop events are in current time interval
                schedule_start = ((e_start >= dt_start.timestamp()) and
                           (e_start < dt_end.timestamp()))
                schedule_end = (e_end <= dt_end.timestamp())

                # has the event a recurrence rule?
                try:
                    rrule = e.rrule.value
                except:
                    rrule = "-"

                logging.debug(
                    'Found event "%s" start: %s end: %s RRule: %s',
                    e.summary.value,
                    e_start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                    e_end_dt.strftime('%Y-%m-%d %H:%M:%S'), rrule)

            # process event only if start or end is in current interval
            if schedule_start or schedule_end:
                logging.info('>>> Schedule event: %s starting at %s'
                             ' (Frequency: %s)<<<',
                             e.summary.value, e_start_dt.strftime("%H:%M"),
                             rrule)
                # clear event options from previous event
                event_options = configparser.ConfigParser()
                try:
                    description = e.description.value
                except:
                    logging.debug('No description for this event')
                    # define empty description to clear previous
                    description = '[DEFAULT]'
                try:
                    event_options.read_string(description)
                    logging.debug('Description: %s', description)
                except:
                    logging.warning('Description incorrect for this event, '
                                    'treating as empty (no options)')

                # logging event options at DEBUG level
                if logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
                    logging.debug('This event options have been found:')
                    for each_section in event_options.sections():
                        logging.debug('Section  %s :', each_section)
                        for (each_key, each_val) in (
                                event_options.items(each_section)):
                            logging.debug('  %s : %s', each_key, each_val)

                r_time_1 = 0
                r_time_2 = 0
                # if there are random numbers define
                if event_options.has_section('random'):
                    if event_options.has_option('random', 'all'):
                        try:
                            # calculate random value from
                            # defined range
                            r_time_1 = uniform(
                                0, float(event_options['random']['all']) * 60)
                            r_time_2 = r_time_1
                        except:
                            logging.error('Random all is incorrect!'
                                          ' Format is "all : 999"')
                    if event_options.has_option('random', 'start'):
                        try:
                            # calculate random value from
                            # defined range
                            r_time_1 = uniform(
                                0, float(event_options['random']['start']) * 60)
                        except:
                            logging.error('Random start is incorrect!'
                                          ' Format is "start : 999"')
                    if event_options.has_option('random', 'end'):
                        try:
                            # calculate random value from defined range
                            r_time_2 = uniform(
                                0, float(event_options['random']['end']) * 60)
                        except:
                            logging.error('Random end is incorrect!'
                                          ' Format is "end : 999"')
                if event_options.has_section('sun'):
                    # first check all possible start options
                    if event_options.has_option('sun', 'start'):
                        if event_options['sun']['start'] == "rise":
                            e_start = rise_time.timestamp()
                        elif event_options['sun']['start'] == "set":
                            e_start = set_time.timestamp()
                        elif event_options['sun']['start'] == "before rise":
                            # start time is after sunrise
                            # = skip event start
                            if e_start > rise_time.timestamp():
                                schedule_start = False
                                logging.debug(
                                    'Defined start is after sun rise, but'
                                    ' should be before -> skipping event')
                        elif event_options['sun']['start'] == "after rise":
                            # start time is before sunrise,
                            # set start = sun rise
                            if e_start < rise_time.timestamp():
                                e_start = rise_time.timestamp()
                                logging.debug(
                                    'Defined start time is before sun rise,'
                                    ' but should be after -> setting start'
                                    ' time = sun rise')
                        elif event_options['sun']['start'] == "before set":
                            # start time is after sun set,
                            # skip event start
                            if e_start > set_time.timestamp():
                                schedule_start = False
                                logging.debug(
                                    'Defined start is after sun set, but'
                                    ' should be before -> skipping event')
                        elif event_options['sun']['start'] == "after set":
                            # start time is before sun set,
                            # set start = sun set
                            if e_start < set_time.timestamp():
                                e_start = set_time.timestamp()
                                logging.debug(
                                    'Defined start time is before sun'
                                    ' set, but should be after ->'
                                    ' setting start time = sun set')
                        else:
                            logging.error(
                                'Sunrise start time option is incorrect,'
                                ' valid options are "rise" or "set"')
                        if event_options.has_option('sun', 'start_offset'):
                            try:  # add start offset
                                # sunrise + offset
                                e_start = e_start+(float(event_options[
                                    'sun']['start_offset']) * 60)
                            except:
                                logging.error(
                                    'Sunrise start offset format is'
                                    ' incorrect! Format is'
                                    ' "start_offset : 999"')
                    # now check all the end options
                    if event_options.has_option('sun', 'end'):
                        if event_options['sun']['end'] == "rise":
                            e_end = rise_time.timestamp()
                        elif event_options['sun']['end'] == "set":
                            e_end = set_time.timestamp()
                        elif event_options['sun']['end'] == "before rise":
                            # end time is after sunrise,
                            # set end = sun rise
                            if e_end > rise_time.timestamp():
                                e_end = rise_time.timestamp()
                                logging.debug(
                                    'Defined end time is after sun'
                                    ' rise, but should be before ->'
                                    ' setting end time = sun rise')
                        elif event_options['sun']['end'] == "after rise":
                            # end time is before sunrise,
                            # set end = sun rise
                            if e_end < rise_time.timestamp():
                                e_end = rise_time.timestamp()
                                logging.debug(
                                    'Defined end time is before sun'
                                    ' rise, but should be after ->'
                                    ' setting end time = sun rise')
                        elif event_options['sun']['end'] == "before set":
                            # end time is after sun set,
                            # set end  = sun set
                            if e_end > set_time.timestamp():
                                e_end = set_time.timestamp()
                                logging.debug(
                                    'Defined end time is after sun '
                                    'set, but should be before ->'
                                    ' setting end time = sun set')
                        elif event_options['sun']['end'] == "after set":
                            # end time is before sun set,
                            # set end = sun set
                            if e_end < set_time.timestamp():
                                e_end = set_time.timestamp()
                                logging.debug(
                                    'Defined end time is before sun'
                                    ' set, but should be after ->'
                                    ' setting end time = sun set')
                        else:
                            logging.error(
                                'Sunrise end time option is '
                                'incorrect, valid options are'
                                ' "rise" or "set"')
                        if event_options.has_option('sun', 'end_offset'):
                            try:  # add end offset
                                # sunset + offset
                                e_end = e_end + (float(event_options[
                                    'sun']['end_offset']) * 60)
                            except:
                                logging.error(
                                    'Sunset end offset format is'
                                    ' incorrect! Format is'
                                    ' "end_offset : 999"')

                # check if calculated start time is after the
                # calculated end time => skip start event
                # (keep end to ensure that "off" is sent)
                if e_start+r_time_1 >= e_end+r_time_2:
                    schedule_start = False
                    logging.debug('Start time is after end time,'
                                  ' skipping start of event.')
                # re-check end time
                # >> not required (causes issues!)
                # schedule_end = (e_end <= dt_end.timestamp())
                if schedule_start:
                    logging.debug(
                        'Switch on %s at %s %+.1f min',
                        e.location.value,
                        datetime.fromtimestamp(e_start+r_time_1).strftime(
                            '%Y-%m-%d %H:%M:%S'),
                        r_time_1 / 60)
                    try:
                        switch_type[config[e.location.value]['type']](
                            e.location.value, True, e_start+r_time_1)
                    except:
                        logging.critical('Error: %s at %s + %s',
                                         e.summary.value,
                                         e_start, r_time_1, '!')
                if schedule_end:
                    logging.debug(
                        'Switch off %s at %s %+.1f min',
                        e.location.value,
                        datetime.fromtimestamp(e_end+r_time_2).strftime(
                            '%Y-%m-%d %H:%M:%S'),
                        r_time_2 / 60)
                    try:
                        switch_type[config[e.location.value]['type']](
                            e.location.value, False, e_end+r_time_2)
                    except:
                        logging.critical('Error for %s at %s+ %s',
                                         e.summary.value, e_end, r_time_2)
                else:
                    logging.debug('End time %s is after current scheduler'
                                  ' interval, skipping end of event.',
                                  datetime.fromtimestamp(
                                      e_end).strftime('%Y-%m-%d %H:%M:%S'))
            else:
                logging.debug('Start and end time are not in current'
                              ' interval, skipping...')
        logging.debug('Scheduler queue:\n%s', s.queue)
        logging.info('Start scheduler at %s',
                     time.strftime('%Y-%m-%d %H:%M:%S'))
        s.run()
        logging.info('<><><> Completed scheduled events'
                     ' for this time interval. <><><>')

    else:
        logging.info('<> No calendar events in this time interval. <>')


if __name__ == '__main__':
    main()
