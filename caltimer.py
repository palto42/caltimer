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
# 2018-10-08                                            #
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
try:
    import RPi.GPIO as GPIO
except ImportError:
    pass  # don't use GPIO as switch output
try:
    from rpi_rf import RFDevice
except ImportError:
    pass  # don't use pri-rf
import argparse
import requests
import serial
from dataclasses import dataclass  # obsolete with Python 3.7


@dataclass
class Interval:
    start: float = 0
    end: float = 0


switch_state = {
    True: "ON",
    False: "OFF",
    }


# Default pulse length definitions
# Can be overwritten from ini file settings
pulse_zap = 187
kopp_time = '00100'

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
                 config[switch]['rf433_tool'])
    if config[switch]['rf433_tool'] == 'codesend':
        s.enterabs(stime, 1, subprocess.call,
                   argument=([config['DEFAULT']['codesend_path'], sendcode,
                              config[switch]['rf433_protocol'],
                              config[switch]['rf433_pulselength']],))
    elif config[switch]['rf433_tool'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code, argument=(
            int(sendcode), int(config[switch]['rf433_protocol']),
            int(config[switch]['rf433_pulselength'])))
    else:
        logging.error(
            'rf_switch undefined rf433_tool for switch %s, check ini file!',
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
                 config[switch]['rf433_tool'])
    if config[switch]['rf433_tool'] == 'codesend':
        s.enterabs(stime, 1, subprocess.call,
                   argument=([config['DEFAULT']['codesend_path'],
                              str(sendcode), "1",
                              config[switch]['rf433_pulselength']],))
    elif config[switch]['rf433_tool'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code,
                   argument=(int(sendcode), 1,
                             config[switch]['rf433_pulselength']))
    else:
        logging.error(
            'rf_comag undefined rf433_tool for switch %s, check ini file!',
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
                 config[switch]['rf433_tool'])
    if config[switch]['rf433_tool'] == "codesend":
        s.enterabs(
            stime, 1, subprocess.call,
            argument=([config['DEFAULT']['codesend_path'],
                       str(sendcode), "1", str(pulse_zap)],))
    elif config[switch]['rf433_tool'] == "rpi-rf":
        s.enterabs(stime, 1, rfdevice.tx_code,
                   argument=(sendcode, 1, pulse_zap))
    else:
        logging.error(
            'rf_zap undefined rf433_tool for switch %s, check ini file!',
            switch)


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


def set_log_level(log_arg):
    loglevel = {
        'CRITICAL': 50,
        'ERROR':    40,
        'WARNING':  30,
        'INFO':     20,
        'DEBUG':    10,
        'NOTSET':    0
    }
    # set logging level
    if log_arg is not None:
        log_arg = log_arg.upper()
        if log_arg not in loglevel:
            log_arg = "ERROR"
            logging.error('Incorrect loging level "%s" specified.', log_arg)
        logging.info('Set loglevel: %s', log_arg)
        logging.getLogger().setLevel(loglevel[log_arg.upper()])


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


def get_sun_time(offset=0):
    # calculate sunrise and sunset times for specified location
    ro = SunriseSunset(
        datetime.now(), latitude=float(config['CALENDAR']['latitude']),
        longitude=float(config['CALENDAR']['longitude']),
        localOffset=offset)
    rise_time, set_time = ro.calculate()
    # overwrite sun times for test purposes
    logging.info('Sunrise %s, sunset %s', rise_time, set_time)
    return rise_time, set_time


def switch_defined(switch):
    if not config.has_section(switch):
        logging.error(
            '>>> Event has an undefined RF-switch "%s"'
            ', skipping this event.',
            switch)
        return False
    elif not config[switch]['rf_type'] in switch_type:
        logging.error(
            '>>> RF-switch "%s" uses undefined type "%s" , '
            'check ini file. Skipping this event.',
            switch, config[switch]['rf_type'])
        return False
    return True


def check_event(event, int_start, int_end):
    # check if the event has a known switch
    # defined in the location field
    # Agruments:
    #   event (dict) : event record to be checked
    #   int_start : start time of current time_interval
    #   int_end : end time of current time_interval
    # Return:
    #   start time in current interval (or None)
    #   end time in current interval (or None)
    #   Random time attribute (if defined)

    if switch_defined(event.location.value):
        # Calculate event start/end time for current date
        # (required for recurring events)
        # TODO: possible issue if interval would span across midnight
        e_time = Interval()
        start_dt = datetime.combine(date.today(),
                                    event.dtstart.value.time())
        end_dt = datetime.combine(date.today(),
                                  event.dtend.value.time())
        e_time.start = start_dt.timestamp()
        e_time.end = end_dt.timestamp()

        # has the event a recurrence rule?
        if hasattr(event, 'rrule'):
            recurrence = event.rrule.value
        else:
            recurrence = "-"

        logging.debug(
            'Found event "%s" start: %s end: %s RRule: %s',
            event.summary.value,
            start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            end_dt.strftime('%Y-%m-%d %H:%M:%S'), recurrence)

        # check if start/stop events are in current time interval
        if (e_time.start < int_start.timestamp() or
                e_time.start >= int_end.timestamp()):
            e_time.start = None
        if e_time.end > int_end.timestamp():
            e_time.end = None
        return e_time
    else:
        logging.error(
            'Switch "%s" undefined for event "%s" at %s',
            event.location.value,
            event.summary.value,
            event.dtstart.value)
        return Interval(None, None)


def get_random(e_time, rnd):
    # rnd = event_options['random']
    rnd_offset = Interval()

    if 'all' in rnd:
        rnd_offset.start = rnd_to_float(rnd, 'all')
        rnd_offset.end = rnd_to_float(rnd, 'all')

    if 'start' in rnd:
        rnd_offset.end = rnd_to_float(rnd, 'end')

    logging.debug("Add random start: %+.1f min, end: %+.1f min",
                  rnd_offset.start/60,
                  rnd_offset.end/60)
    if e_time.start is not None:
        e_time.start = e_time.start + rnd_offset.start
    if e_time.end is not None:
        e_time.end = e_time.end + rnd_offset.end
    return e_time


def rnd_to_float(list, index):
    try:
        # calculate random value in seconds from defined range in minutes
        return uniform(0, float(list[index]) * 60)
    except ValueError:
        logging.error('Random "%s: %s" is incorrect! Format is "all : 999"',
                      index, list[index])
        return 0


def time_to_str(time):
    try:
        return datetime.fromtimestamp(time)
    except TypeError:
        return "None"


def int_to_str(interval):
    try:
        int_str = datetime.fromtimestamp(
            interval.start).strftime("%Y-%m-%d %H:%M:%S") + " to "
    except TypeError:
        int_str = "None to "
    try:
        int_str += datetime.fromtimestamp(
            interval.end).strftime("%Y-%m-%d %H:%M:%S")
    except TypeError:
        int_str += "None"
    return int_str


def use_sun(e_time, sun_opt, time_interval):
    get_sun = {
        "rise": sun_rise,
        "before rise": before_rise,
        "after rise": after_rise,
        "set": sun_set,
        "before set": before_set,
        "after set": after_set,
    }
    # check sun start option
    if (e_time.start is not None and
            'start' in sun_opt and
            sun_opt['start'] in get_sun):
        if ('start_offset' in sun_opt):
            offset = sun_opt['start_offset']
        else:
            offset = 0
        e_time.start = check_interval(
            get_sun[sun_opt['start']](e_time.start, True, offset),
            time_interval)
    # now check sun end option
    if (e_time.end is not None and
            'end' in sun_opt and
            sun_opt['end'] in get_sun):
        if ('end_offset' in sun_opt):
            offset = sun_opt['end_offset']
        else:
            offset = 0
        e_time.end = check_interval(
            get_sun[sun_opt['end']](e_time.end, False, offset),
            time_interval)
    return e_time


def check_interval(time, time_interval):
    # ensure that the tim is within the current interval
    if time is not None:
        time = max(time, time_interval.start.timestamp())
        time = min(time, time_interval.end.timestamp())
    return time


def sun_rise(time, start, offset):
    logging.debug("%s event at %s uses sun rise at %s.",
                  switch_state[start],
                  time_to_str(time),
                  time_to_str(add_offset(rise_time.timestamp(), offset)))
    return max(time, add_offset(rise_time.timestamp(), offset))


def before_rise(time, start, offset):
    t = add_offset(rise_time.timestamp(), offset)
    if time > t:
        if start:
            # skip start event
            return None
        else:
            return t
    else:
        if start:
            return t
        else:
            return time


def after_rise(time, start, offset):
    t = add_offset(rise_time.timestamp(), offset)
    if time < rise_time.timestamp():
        logging.debug("Time %s < after rise %s, setting to rise",
                      time,
                      t)
        return t
    else:
        logging.debug("Time %s >= after rise %s, keep time",
                      time,
                      t)
        return time


def sun_set(time, start, offset):
    logging.debug("%s event at %s uses sun set at %s.",
                  switch_state[start],
                  time_to_str(time),
                  time_to_str(add_offset(set_time.timestamp(), offset)))
    return min(time, add_offset(set_time.timestamp(), offset))


def before_set(time, start, offset):
    t = add_offset(set_time.timestamp(), offset)
    if time > t:
        if start:
            return None
        else:
            return t
    else:
        if start:
            return t
        else:
            return time


def after_set(time, start, offset):
    t = add_offset(set_time.timestamp(), offset)
    if time < t:
        return t
    else:
        return time


def add_offset(time, offset):
    try:  # add start offset
        # sunrise + offset
        o_time = time+(float(offset) * 60)
    except ValueError:
        o_time = time
        logging.error(
            'Sun offset format is incorrect! Format is'
            ' "xxx_offset : 999"')
    return o_time


def schedule_switch(time, switch, status):
    if time is not None:
        logging.debug(
            'Switch %s %s at %s',
            switch_state[status],
            switch,
            datetime.fromtimestamp(
                time).strftime(
                '%Y-%m-%d %H:%M:%S'))
        if config[switch]['rf_type'] in switch_type:
            switch_type[config[switch]['rf_type']](switch, status, time)
        else:
            logging.critical(
                'RF type "%s" of switch "%s" is undefined!',
                config[switch]['rf_type'],
                switch)
    else:
        logging.debug(
            '%s time for switch "%s" is not in current time interval.',
            switch_state[status], switch)


#############################################################
# MAIN                                                      #
#############################################################
def main():

    # Switch command options
    # usage: switch_type[type]()
    global switch_type
    switch_type = {
        'rf433': rf_switch,
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
    if config.has_option('LOGGING', 'logfile'):
        open_log_file(config['LOGGING']['logfile'])
    set_log_level(args.log)

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
            ser = open("/tmp/serial.txt", "wb")
            logging.error("Can't open serial port %s, check ini file "
                          "(writing to /tmp/serial.txt instead)",
                          config['DEFAULT']['ser_port'])
    else:
        ser = open("/tmp/serial.txt", "wb")

    # Enable RF transmitter
    global rfdevice
    if config.has_option('DEFAULT', 'rf433_gpio'):
        rfdevice = RFDevice(int(config['DEFAULT']['rf433_gpio']))
        rfdevice.enable_tx()
    else:
        logging.info('No GPIO for RF433 tool "rpi-rf" defined.')

    # Time zone offset
    tzoffset = datetime.today().hour-datetime.utcnow().hour

    # get coordinates from address
    if args.address is not None:
        config.set('CALENDAR', 'location', args.address)
        get_location(args.init, args.address)

    # Set Caldav url
    if config.has_option('CALENDAR', 'caldav'):
        url = config['CALENDAR']['caldav']
    else:
        logging.error('Missing caldav URL in config file,'
                      ' please check %s', args.init)
        return

    interval = Interval()
    # Scheduler interval in minutes
    try:
        if args.time_interval is not None:
            interval_span = int(args.time_interval)
        else:
            interval_span = int(config['DEFAULT']['interval'])
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
    interval.start = dt + timedelta(
        minutes=interval_span - dt.minute % interval_span,
        seconds=-(dt.second % 60),
        microseconds=-(dt.microsecond % 1000000))
    interval.end = interval.start + timedelta(minutes=interval_span)

    logging.info("Get events between: %s and %s", interval.start, interval.end)
    results = calendar.date_search(
        interval.start - timedelta(hours=tzoffset),
        interval.end - timedelta(hours=tzoffset))
    logging.debug('%s events found for defined period.', len(results))

    if len(results) > 0:
        # check if longitude/latitude is set in ini file
        # otherwise use location to query them from google maps
        if not (config.has_option('CALENDAR', 'latitude') and
                config.has_option('CALENDAR', 'longitude')):
            if config.has_option('CALENDAR', 'location'):
                logging.info('Get coordinates from location address')
                get_location(args.init, config['CALENDAR']['location'])
            else:
                logging.error('Coordinates and location not defined, exit')
                return

        # get sunrise and sunset
# maybe change to struct "sun.rise" und "sun.set" ?
        global rise_time
        global set_time
        rise_time, set_time = get_sun_time(tzoffset)
        if args.sun_rise is not None:
            rise_time = datetime.strptime(
                str(date.today())+" "+args.sun_rise, "%Y-%m-%d %H:%M")
        if args.sun_set is not None:
            set_time = datetime.strptime(
                str(date.today())+" "+args.sun_set, "%Y-%m-%d %H:%M")

        # schedule events
        logging.debug('Define scheduler')
        global s
        s = sched.scheduler(time.time, time.sleep)
        for event in results:
            event.load()
            e = event.instance.vevent

            e_time = check_event(e, interval.start, interval.end)

            # process event only if start or end is in current interval
            if e_time.start is not None or e_time.end is not None:
                logging.info('>>> Schedule event: %s starting at %s <<<<',
                             e.summary.value, e.dtstart.value)
                # clear event options from previous event
                event_options = configparser.ConfigParser()
                if hasattr(e, 'description'):
                    description = e.description.value
                else:
                    logging.debug('No description for this event')
                    # define empty description to clear previous
                    description = '[DEFAULT]'
                try:
                    # parse event options in desctription text
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

                # check sun options
                logging.debug('Initial event time: %s',
                              int_to_str(e_time))
                if (event_options.has_section('sun')):
                    e_time = use_sun(e_time,
                                     event_options['sun'],
                                     interval)
                logging.debug('After processing "sun" section: %s',
                              int_to_str(e_time))
                # if there are random numbers define
                if event_options.has_section('random'):
                    e_time = get_random(e_time, event_options['random'])
                logging.debug('After processing "random" section: %s',
                              int_to_str(e_time))
                # check if calculated start time is after the
                # calculated end time => skip start event
                # (keep end to ensure that "off" is sent)
                if (e_time.start is not None and e_time.end is not None and
                        e_time.start >= e_time.end):
                    e_time.start = None
                    logging.debug('Start time is after end time,'
                                  ' skipping start of event.')

                # schedule_time.end = (e_time.end <= interval.end.timestamp())
                schedule_switch(e_time.start, e.location.value, True)
                schedule_switch(e_time.end, e.location.value, False)
            else:
                logging.debug('Start and end time are not in current'
                              ' interval, skipping...')
        logging.debug('Scheduler queue:\n%s', s.queue)
        logging.info('Start scheduler at %s',
                     time.strftime('%Y-%m-%d %H:%M:%S'))
        s.run()
        logging.info('<><><> Completed scheduled events'
                     ' for this time interval. <><><>')
        if ser is not None:
            ser.close()

    else:
        logging.info('<> No calendar events in this time interval. <>')


if __name__ == '__main__':
    main()
