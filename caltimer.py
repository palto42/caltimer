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
# 2018-10-07                                            #
# #######################################################

import logging
import sys
import errno
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
import requests
import serial

# Default pulse length definitions
# Can be overwritten from ini file settings
pulse_comag = 350
pulse_zap = 187
kopp_time = '00100'
switch_state = {
    True: "ON",
    False: "OFF",
    }

# set initial logging to stderr, level INFO
logging.basicConfig(
    stream=sys.stderr,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    level=logging.INFO)


def send_ser(code):
    try:
        ser.write(code.encode()+b'\n')
        logging.debug('Serial send code = %s', code)
    except serial.SerialException:
        logging.error("Tried to send code %s, "
                      "but serial port not defined or available.", code)


def rf_switch(switch, onoff, stime):
    if onoff:
        sendcode = config[switch]['oncode']
    else:
        sendcode = config[switch]['offcode']
    logging.info('<<< rf_switch schedule to send %s code %s '
                 'for switch %s at time %s via %s',
                 switch_state[onoff], sendcode, switch,
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
    # switch OFF = "0" = binary "01" = tri-state "F"
    # switch ON  = "1" = binary "00" = tri-state "0"
    # ON  = binary "0001" = tri-state "0F"
    # OFF = binary "0100" = tri-state "F0"
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
    logging.info('<<< rf_comag schedule to send %s code %s '
                 'for switch %s at time %s via %s',
                 switch_state[onoff], sendcode, switch,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        s.enterabs(stime, 1, subprocess.call,
                   argument=([config['DEFAULT']['rf433'],
                              str(sendcode), "1", str(pulse_comag)],))
    elif config[switch]['rf_code'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code,
                   argument=(int(sendcode), 1, pulse_comag))
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
    logging.info('<<< rf_zap schedule to send %s code %s '
                 'for switch %s at time %s via %s',
                 switch_state[onoff], sendcode, switch,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        s.enterabs(
            stime, 1, subprocess.call,
            argument=([config['DEFAULT']['rf433'],
                       str(sendcode), "1", str(pulse_zap)],))
    elif config[switch]['rf_code'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code,
                   argument=(sendcode, 1, pulse_zap))
    else:
        logging.error(
            'rf_zap undefined rf_code for switch %s, check ini file!', switch)


def rf_kopp(switch, onoff, stime):
    # Kopp code example
    #
    # kt004B130300100N
    # |||||||||||||||+-- Print output J/N
    # ||||||||||+++++--- Key pressed in ms
    # ||||++++++-------- Transmitter Code 1 + 2
    # ||++-------------- Key code on/off
    # ++---------------- kt = nanocul command for Kopp transmit

    sendcode = 'kt'
    if onoff:
        if config.has_option(switch, 'key_on'):
            sendcode += config[switch]['key_on']
        else:
            # calculate key_on from key_off by adding 0x10
            sendcode += format(int(config[switch]['key_off'], base=16)+16, 'X')
    else:
        sendcode += config[switch]['key_off']
    sendcode += (config[switch]['transmit_1']
                 + config[switch]['transmit_2']
                 + kopp_time + 'N')
    s.enterabs(stime, 1, send_ser, argument=(sendcode,))
    logging.info('<<< rf_kopp schedule to send %s code %s '
                 'to nanocul for switch % s at time %s',
                 switch_state[onoff], sendcode, switch,
                 time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)))


def gpio_switch(switch, onoff, stime):
    # Set the pin to output (just to be sure...)
    try:
        GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except RuntimeError as e:
        logging.error('GPIO setup error for pin %d, error message: %s',
                      config[switch]['pin'],
                      e.message)
    # Can directly use the Boolean variable onoff since True=1=GPIO.HIGH
    s.enterabs(stime, 1, GPIO.output,
               argument=(int(config[switch]['pin']), onoff))
    logging.info('<<< Schedule GPIO %s %s at %s', config[switch]['pin'],
                 onoff, time.strftime('%H:%M:%S', time.localtime(stime)))


def gpio_pulse(switch, onoff, stime):
    # Set the pin to output (just to be sure...)
    try:
        GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except RuntimeError:
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


def open_log_file(file):
    # check if logfile is defined and can be opened for write/append
    # file = config['LOGGING']['logfile']
    try:
        logfile = open(file, 'a')
        logfile.close()
        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        # Reconfigure logging again, this time with a file.
        logging.basicConfig(
            filename=file,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    except IOError as x:
        if x.errno == errno.EACCES:
            temp_log = file[:-4] \
                + time.strftime("_%y-%m-%d_%H-%M")+".log"
            logging.error(
                'No write access to logfile, '
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
            except IOError:
                logging.error(
                    'No write access for temp logfile, '
                    'using sdterr for logging.')
        else:
            logging.error('No (correct) filename defined, '
                          'using sdterr for logging.')


def set_log_level(log_arg, update, file):
    loglevel = {
        'CRITICAL': 50,
        'ERROR':    40,
        'WARNING':  30,
        'INFO':     20,
        'DEBUG':    10,
        'NOTSET':    0
    }
    # set logging level
    log_arg = log_arg.upper()
    if log_arg not in loglevel:
        log_arg = "ERROR"
        logging.error('Incorrect loging level "%s" specified.', log_arg)
    logging.info('Set loglevel: %s', log_arg)
    logging.getLogger().setLevel(loglevel[log_arg.upper()])
    if update and log_arg in loglevel:
        config.set('LOGGING', 'loglevel', log_arg.upper())
        update_ini(file)


def get_location(file, address):
    response = requests.get(
        'https://maps.googleapis.com/maps/api/geocode/json?address='+address)
    resp_json_payload = response.json()
    latitude = resp_json_payload['results'][0]['geometry']['location']['lat']
    longitude = resp_json_payload['results'][0]['geometry']['location']['lng']
    logging.info('Found coordinates for address %s: latitude=%s, longitude=%s',
                 address, latitude, longitude)
    config.set('CALENDAR', 'latitude', str(latitude))
    config.set('CALENDAR', 'longitude', str(longitude))


def update_ini(file):
    logging.warning('Saving updates to ini file')
    # Note: writing the ini file will remove all comments!
    with open(file, 'w') as configfile:
        config.write(configfile)


def get_sun(offset, m_rise, m_set):
    # calculate sunrise and sunset times for specified location
    ro = SunriseSunset(
        datetime.now(), latitude=float(config['CALENDAR']['latitude']),
        longitude=float(config['CALENDAR']['longitude']),
        localOffset=offset)
    rise_time, set_time = ro.calculate()
    # overwrite sun times for test purposes
    if m_rise is not None:
        rise_time = datetime.strptime(str(date.today())+" "+m_rise,
                                      "%Y-%m-%d %H:%M")
    if m_set is not None:
        set_time = datetime.strptime(str(date.today())+" "+m_set,
                                     "%Y-%m-%d %H:%M")
    logging.info('Sunrise %s, sunset %s', rise_time, set_time)
    return rise_time, set_time


def switch_defined(switch):
    if not config.has_section(switch):
        logging.error(
            '>>> Event has an undefined RF-switch "%s"'
            ', skipping this event.',
            switch)
        return False
    elif not config[switch]['type'] in switch_type:
        logging.error(
            '>>> RF-switch "%s" uses undefined type "%s" , '
            'check ini file. Skipping this event.',
            switch, config[switch]['type'])
        return False
    return True


#############################################################
# MAIN                                                      #
#############################################################
def main():

    # Switch command options
    # usage: switch_type[type]()
    global switch_type
    switch_type = {
        'rf':    rf_switch,
        'comag': rf_comag,
        'zap':   rf_zap,
        'kopp':  rf_kopp,
        'gpio':  gpio_switch,
        'pulse': gpio_pulse,
        'dummy': dummy_switch,
        }

    # Raspberry Pi GPIO settings
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

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
    parser.add_argument('-a', '--address',
                        help='Get coordinates from address')
    parser.add_argument('-u', '--update',
                        help='Update ini file (e.g. log level)',
                        action='store_true')
    args = parser.parse_args()

    # Read ini file for RC switch definition
    # keys: oncode, offcode, protocol, pulselength
    # example: config['switchname']['oncode']
    global config
    config = configparser.ConfigParser()
    config.sections()
    config.read(args.init)
    if len(config) <= 1:
        print("ERROR: The specified ini file doesn't exit!")
        return

    # set logfile destination and log level
    open_log_file(config['LOGGING']['logfile'])
    set_log_level(args.log, args.update, args.init)

    if config.has_option('DEFAULT', 'pulselength'):
        pulse_comag = int(config['DEFAULT']['pulselength'])
        logging.debug('Setting pulse_comag = %s', pulse_comag)

    if config.has_option('DEFAULT', 'zap_pulse'):
        pulse_zap = int(config['DEFAULT']['zap_pulse'])
        logging.debug('Setting pulse_zap = %s', pulse_zap)

    if config.has_option('DEFAULT', 'kopp_time'):
        kopp_time = config['DEFAULT']['kopp_time'].zfill(5)
        logging.debug('Setting kopp_time = %s', kopp_time)

    if config.has_option('DEFAULT', 'ser_port'):
        try:
            logging.debug('Create serial interface %s',
                          config['DEFAULT']['ser_port'])
            global ser
            ser = serial.Serial(config['DEFAULT']['ser_port'],
                                38400, timeout=0)
        except serial.SerialException:
            logging.error("Can't open serial port %s, check ini file.",
                          config['DEFAULT']['ser_port'])

    # Enable RF transmitter
    global rfdevice
    rfdevice = RFDevice(int(config['DEFAULT']['gpio']))
    rfdevice.enable_tx()

    # Time zone offset
    tzoffset = datetime.today().hour-datetime.utcnow().hour

    # get coordinates from address
    if args.address is not None:
        config.set('CALENDAR', 'location', args.address)
        get_location(args.init, args.address)
        if args.update:
            update_ini(args.init)

    # Set Caldav url
    if config.has_option('CALENDAR', 'caldav'):
        url = config['CALENDAR']['caldav']
    else:
        logging.error('Missing caldav URL in config file,'
                      ' please check %s', args.init)
        return

    # Scheduler interval in minutes
    try:
        if args.time_interval is not None:
            interval = int(args.time_interval)
            if args.update:
                config.set('CALENDAR', 'interval', args.time_interval)
                update_ini(args.init)
        else:
            interval = int(config['CALENDAR']['interval'])
    except ValueError:
        logging.error(
            'Defined scheduler time interval is not an integer number!')
        return

    # event options
    event_options = configparser.ConfigParser()

    # try to access the web calendar
    client = caldav.DAVClient(url)
    try:
        principal = client.principal()
    except requests.exceptions.RequestException as e:
        logging.error('Error to access the web calendar: %s', e.message)
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
    dt_start = dt + timedelta(
        minutes=interval - dt.minute % interval,
        seconds=-(dt.second % 60),
        microseconds=-(dt.microsecond % 1000000))
    dt_end = dt_start + timedelta(minutes=interval)

    logging.info("Get events between: %s and %s", dt_start, dt_end)
    results = calendar.date_search(
        dt_start - timedelta(hours=tzoffset),
        dt_end - timedelta(hours=tzoffset))
    logging.debug('%s events found for defined period.', len(results))

    # is below required? Seems to be set again later
    r_time_1 = 0
    r_time_2 = 0

    if len(results) > 0:
        # check if longitude/latitude is set in ini file
        # otherwise use location to query them from google maps
        if not (config.has_option('CALENDAR', 'latitude') and
                config.has_option('CALENDAR', 'longitude')):
            if config.has_option('CALENDAR', 'location'):
                logging.info('Get coordinates from location address')
                get_location(args.init, config['CALENDAR']['location'])
                if args.update:
                    update_ini(args.init)
            else:
                logging.error('Coordinates and location not defined, exit')
                return

        # get sunrise and sunset
        rise_time, set_time = get_sun(tzoffset, args.sun_rise, args.sun_set)

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
            if switch_defined(e.location.value):
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
                schedule_start = (
                    (e_start >= dt_start.timestamp()) and
                    (e_start < dt_end.timestamp()))
                schedule_end = (e_end <= dt_end.timestamp())
                # has the event a recurrence rule?
                if hasattr(e, 'rrule'):
                    rrule = e.rrule.value
                else:
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
                if hasattr(e, 'description'):
                    description = e.description.value
                else:
                    logging.debug('No description for this event')
                    # define empty description to clear previous
                    description = '[DEFAULT]'
                try:
                    event_options.read_string(description)
                    logging.debug('Description: %s', description)
                except configparser.Error as e:
                    logging.warning(
                        'Description incorrect (%s) for this event, '
                        'treating as empty (no options)', e.message)

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
                        except ValueError:
                            logging.error('Random all is incorrect!'
                                          ' Format is "all : 999"')
                    if event_options.has_option('random', 'start'):
                        try:
                            # calculate random value from
                            # defined range
                            r_time_1 = uniform(
                                0,
                                float(event_options['random']['start']) * 60)
                        except ValueError:
                            logging.error('Random start is incorrect!'
                                          ' Format is "start : 999"')
                    if event_options.has_option('random', 'end'):
                        try:
                            # calculate random value from defined range
                            r_time_2 = uniform(
                                0, float(event_options['random']['end']) * 60)
                        except ValueError:
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
                            except ValueError:
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
                            except ValueError:
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
                        logging.critical(
                            'Error: %s at %s + %s', e.summary.value,
                            datetime.fromtimestamp(e_start).strftime(
                                '%Y-%m-%d %H:%M:%S'),
                            r_time_1, '!')
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
                        logging.critical(
                            'Error for %s at %s + %s',
                            e.summary.value,
                            datetime.fromtimestamp(e_end).strftime(
                                '%Y-%m-%d %H:%M:%S'),
                            r_time_2)
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
        try:
            ser.close()
        finally:
            logging.debug('No serial used, nothing to close.')
    else:
        logging.info('<> No calendar events in this time interval. <>')


if __name__ == '__main__':
    main()
