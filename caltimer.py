#!/usr/bin/python3

#########################################################  
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
# 2017-10-05                                            #
#########################################################

import logging
import sys
import configparser
import subprocess
import sched
import time
from datetime import datetime, date, timedelta
from random import uniform
import caldav
from caldav.elements import dav, cdav
from sunrise_sunset import SunriseSunset
import RPi.GPIO as GPIO
from rpi_rf import RFDevice
import argparse

# set initial logging to stderr, level INFO
logging.basicConfig(stream=sys.stderr, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s', level=logging.INFO)


def rf_switch(switch,onoff,stime):
    if onoff:
      sendcode=config[switch]['oncode']
    else:
      sendcode=config[switch]['offcode']
    logging.info('<<< rf_switch schedule to send RF code %s at time %s via %s',
        sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
      s.enterabs(stime,1,subprocess.call, argument=([config['DEFAULT']['rf433'],sendcode, 
          config[switch]['protocol'], config[switch]['pulselength']],));
    elif config[switch]['rf_code'] == "rpi-rf":
      s.enterabs(stime,1,rfdevice.tx_code, argument=(int(sendcode), 
          int(config[switch]['protocol']), int(config[switch]['pulselength'])));
    else:
      logging.error('rf_switch undefined rf_code for switch %s, check ini file!',switch)

def rf_comag(switch,onoff,stime):
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
    logging.debug('*** Comag binary code = %s',bincode)
    # translate
    sendcode = 0
    for c in bincode:
      sendcode = sendcode << 2
      if c == "0":
        sendcode = sendcode | 1
    logging.debug('*** Comag sendcode = %s','{:08b}'.format(sendcode))   
    logging.info('<<< rf_comag schedule to send RF code %s at time %s via %s',
        sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),config[switch]['rf_code']);
    if config[switch]['rf_code'] == "rf433":
      s.enterabs(stime,1,subprocess.call,
        argument=([config['DEFAULT']['rf433'],str(sendcode),"1","350"],));
    elif config[switch]['rf_code'] == "rpi-rf":
      s.enterabs(stime,1,rfdevice.tx_code,argument=(int(sendcode), 1, 350));
    else:
      logging.error('rf_comag undefined rf_code for switch %s, check ini file!',switch)

def rf_zap(switch,onoff,stime):
    # ZAP/REV code calculation:
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
    # binary     00  00  01  01  01| 11  01  01  00  00| 00  11 = 000001010111010100000011

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
    key_code [5-int(config[switch]['key'])] = "1"
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
    logging.debug('*** ZAP sendcode = %s','{:08b}'.format(sendcode))
    logging.info('<<< rf_zap schedule to send RF code %s at time %s via %s',
        sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)),config[switch]['rf_code']);
    if config[switch]['rf_code'] == "rf433":
      s.enterabs(stime,1,subprocess.call,
        argument=([config['DEFAULT']['rf433'],str(sendcode),"1","188"],));
    elif config[switch]['rf_code'] == "rpi-rf":
      s.enterabs(stime,1,rfdevice.tx_code,argument=(sendcode, 1, 188));
    else:
      logging.error('rf_zap undefined rf_code for switch %s, check ini file!',switch)

def gpio_switch(switch,onoff,stime):
# Set the pin to output (just to be sure...)
    try:
      GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except:
      logging.error('GPIO setup error for pin %d',config[switch]['pin'])
# Can directly use the Boolean variabe onoff since True=1=GPIO.HIGH
    s.enterabs(stime,1,GPIO.output,argument=(int(config[switch]['pin']),onoff));
    logging.info ('<<< Schedule GPIO %s %s at %s',config[switch]['pin'],onoff,time.strftime('%H:%M:%S', time.localtime(stime)));

def gpio_pulse(switch,onoff,stime):
# Set the pin to output (just to be sure...)
    try:
      GPIO.setup(int(config[switch]['pin']), GPIO.OUT)
    except:
      logging.error('GPIO setup error for pin %d',config[switch]['pin'])
# Get the duration of the pulse
    if onoff:
      pulsetime=float(config[switch]['on'])
    else:
      pulsetime=float(config[switch]['off'])
# Chek for maximum pulse length, e.g. 10s (configured in config.ini)
    if pulsetime>float(config['DEFAULT']['max_pulse']):
      logging.error('The pulse duration of %s s is too long, setting to max= %s',pulsetime,config['DEFAULT']['max_pulse']);
      pulsetime=float(config['DEFAULT']['max_pulse']);
    logging.info ('<<< Schedule GPIO %s pulse %s at %s',config[switch]['pin'],onoff,time.strftime('%H:%M:%S', time.localtime(stime)));
    s.enterabs(stime,1,GPIO.output,argument=(int(config[switch]['pin']),1));
    s.enterabs(stime+pulsetime,1,GPIO.output,argument=(int(config[switch]['pin']),0));

def dummy_switch(switch,onoff,stime):
    s.enterabs(stime,1,logging.warning,argument=('Dummy: %s',onoff));

# Switch command options
# usage: switch_type[type]()
switch_type = {
  'rf'    : rf_switch,
  'comag' : rf_comag,
  'zap'   : rf_zap,
  'gpio'  : gpio_switch,
  'pulse' : gpio_pulse,
  'dummy' : dummy_switch,
  }
 
loglevel = {
  'CRITICAL' : 50,
  'ERROR'    : 40,
  'WARNING'  : 30,
  'INFO'     : 20,
  'DEBUG'    : 10,
  'NOTSET'   :  0
}


#############################################################
# MAIN                                                      #
#############################################################
def main():

  # Comamnd line arguments
  # -i ini-file path/name
  # -d debug level
  parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
  parser.add_argument('-i', '--init', help='specify path/filename of ini file to read from',
      default='/etc/caltimer/caltimer.ini')
  parser.add_argument('-l', '--log', help='set log level (overwrites ini file)\n'
      '  Supported levels are: CRITICAL, ERROR, WARNING, INFO, DEBUG')
  args = parser.parse_args()

  # Read ini file for RC switch definition
  # keys: oncode, offcode, protocol, pulselength
  # example: config['switchname']['oncode']
  global config
  config = configparser.ConfigParser()
  config.sections()
  config.read(args.init)
  if len(config)<=1:
      print ("ERROR: The specified ini file doesn't exit!")
      return

  # Raspberry Pi GPIO settings
  GPIO.setmode(GPIO.BCM)
  GPIO.setwarnings(False)

  # Enable RF transmitter
  global rfdevice 
  rfdevice = RFDevice(int(config['DEFAULT']['gpio']))
  rfdevice.enable_tx()

  # Timezone offset
  tzoffset = datetime.today().hour-datetime.utcnow().hour

  # set logfile
    
  try:
    # check if logfile is defined and can be opened for read
    logfile=open(config['LOGGING']['logfile'],'r')
    logfile.close()
    log_exists = True
#    print ('File exists',log_exists)
  except:
    log_exists = False
  try:
    # check if logfile is defined and can be opened for write/append
    logfile=open(config['LOGGING']['logfile'],'a')
    logfile.close()
    # Remove all handlers associated with the root logger object.
    for handler in logging.root.handlers[:]:
      logging.root.removeHandler(handler)
    # Reconfigure logging again, this time with a file.
    logging.basicConfig(filename = config['LOGGING']['logfile'], level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
  except:
    if log_exists:
      temp_log = config['LOGGING']['logfile'][:-4]+time.strftime("_%y-%m-%d_%H-%M")+".log"
      logging.error('Logfile is already in use by other process, using temp logfile: %s',temp_log)
      try: # try to open new logfile write
        logfile=open(temp_log,'w')
        logfile.close()
        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
          logging.root.removeHandler(handler)
        # Reconfigure logging again, this time with a file.
        logging.basicConfig(filename = temp_log, level=logging.INFO, format='%(asctime)s - %(module)s - %(levelname)s : %(message)s')
      except:
        logging.error('No write access for temp logfile, using sdterr for logging.') 
    else:
      logging.error('No (correct) filename defined, using sdterr for logging.')
  if args.log is not None:
    # log level set as command line parameter
    try:
      logging.info('Set loglevel: %s',args.log)
      logging.getLogger().setLevel(loglevel[args.log])
    except:
      print ('ERROR: Incorrect loging level specified, using log evel "ERROR"')
      logging.getLogger().setLevel(logging.ERROR)
  else:
    # set logging level if defined in caltimer.ini
    logging.info('-----------------------------------------------------------------')
    try:
      logging.info('Set loglevel: %s',config['LOGGING']['loglevel'])
      logging.getLogger().setLevel(loglevel[config['LOGGING']['loglevel']])
    except:
      logging.error('No loglevel defined, using ERROR')
      logging.getLogger().setLevel(logging.ERROR)
 
  # Caldav url
  try:
    url = config['CALENDAR']['caldav']
  except:
    logging.error('Missing or incorrect ini file, please check /etc/caltimer/caltimer.ini')
    return
  # Scheduler intervall in Minuten
  interval = int(config['CALENDAR']['interval'])
  # Maximum pulse length for GPIO pulses
  # max_pulse = float(config['DEFAULT']['max_pulse'])

  # event options
  event_options = configparser.ConfigParser()


  client = caldav.DAVClient(url)
  try:
    principal = client.principal()
  except:
    e = sys.exc_info()[0]
    logging.error('Error to access the web calendar: %s', e )
    return
  calendars = principal.calendars()
  if len(calendars) == 0:
    logging.error('No calender found at URL: %s',url)
    return
  
  if len(calendars) > 0:
    calendar = next((c for c in calendars if c.name == config['CALENDAR']['calname']), None)
    if calendar is  None:
      logging.error('Calendar %s not found.',config['CALENDAR']['calname'])
      logging.error('Available calendars:')
      for calendar in calendars:
        logging.error('  %s ',calendar.name)
      return
    logging.info("Using calendar %s", calendar)

    dt = datetime.today()
    dt = dt + timedelta(minutes = interval - dt.minute % interval, seconds = -(dt.second % 60), microseconds = -(dt.microsecond % 1000000))
    dt_end = dt+timedelta(minutes=interval)
    dt_ts = dt.timestamp()
    dt_end_ts = dt_end.timestamp()

    logging.info("Events between: %s and %s",dt,dt_end)

    results = calendar.date_search(
        dt - timedelta(hours=tzoffset), dt_end - timedelta(hours=tzoffset) )

    r_time_1 = 0
    r_time_2 = 0
    
    logging.debug('%s events found for defined period.',len(results))
    if len(results)>0:
      # calculate sunrise and sunset
      ro = SunriseSunset(datetime.now(), latitude=float(config['CALENDAR']['latitude']),
          longitude=float(config['CALENDAR']['longitude']), localOffset=float(config['CALENDAR']['local_offset']))
      rise_time, set_time = ro.calculate()
      logging.debug('Sunrise %s, sunset %s',rise_time, set_time)

      # schedule events
      logging.debug('Define scheduler')
      global s
      s = sched.scheduler(time.time, time.sleep)
      for event in results:
        event.load()
        e = event.instance.vevent
        if not config.has_section(e.location.value):
          logging.error ('>>> Event "%s" at %s has an undefined RF-switch "%s", skipping this event.',
            e.summary.value, e.dtstart.value.strftime("%H:%M"), e.location.value)
        elif not config[e.location.value]['type'] in switch_type:
          logging.error ('>>> RF-switch "%s" uses undefined type "%s" , check ini file. Skipping this event.',
            e.location.value, config[e.location.value]['type'])
        else:
##################################################################################################################
          # Calculate event start time for current date (required for recurring events)
          e_start_dt = datetime.combine(date.today(),e.dtstart.value.time())
          e_start = e_start_dt.timestamp()
          # Calculate event end time for current date (required for recurring events)
          e_end_dt = datetime.combine(date.today(),e.dtend.value.time())
          e_end = e_end_dt.timestamp()
          # check if start/stop events are in current time interval
          s_start = e_start >= dt_ts and e_start < dt_end_ts
          s_end = e_end >= dt_ts and e_end <= dt_end_ts
          logging.debug('Event "%s" start: %s end: %s RRule: %s',
              e.summary.value,e_start_dt.strftime('%Y-%m-%d %H:%M:%S'),e_end_dt.strftime('%Y-%m-%d %H:%M:%S'), e.rrule.value)            

          if s_start or s_end: # process event only if start or end is in current interval
            logging.info('>>> Schedule event: %s starting at %s (Frequency: %s)<<<',e.summary.value,e_start_dt.strftime("%H:%M"),e.rrule.value)
            event_options = configparser.ConfigParser() # clear event options from previous event
            try:
              description = e.description.value
            except:
              logging.debug('No description for this event')
              description = '[DEFAULT]' # define empyt description to clear previous
            try:
              event_options.read_string(description)
              logging.debug('Description: %s',description)
            except:
              logging.warning('Description incorrect for this event, treating as empty (no options)')

            # logging event options at DEBUG level
            if  logging.getLogger().getEffectiveLevel() <= logging.DEBUG:
              logging.debug('This event options have been found:')
              for each_section in event_options.sections():
                logging.debug ('Section  %s :',each_section)
                for (each_key, each_val) in event_options.items(each_section):
                  logging.debug ('  %s : %s',each_key,each_val)

            r_time_1 = 0
            r_time_2 = 0
            # if there are random numbers define
            if event_options.has_section('random'):
              if event_options.has_option('random','all'):
                try:
                  r_time_1 = uniform(0,float(event_options['random']['all'])*60) # calculate random value from defined range
                  r_time_2 = r_time_1
                except:
                  logging.error('Random all is incorrect! Format is "all : 999"')
              if event_options.has_option('random','start'):
                try:
                  r_time_1 = uniform(0,float(event_options['random']['start'])*60) # calculate random value from defined range
                except:
                  logging.error('Random start is incorrect! Format is "start : 999"')
              if event_options.has_option('random','end'):
                try:
                  r_time_2 = uniform(0,float(event_options['random']['end'])*60) # calculate random value from defined range
                except:
                  logging.error('Random end is incorrect! Format is "end : 999"')
            if event_options.has_section('sun'):
              if event_options.has_option('sun','start'):
                if event_options['sun']['start'] == "rise":
                  e_start=rise_time.timestamp()
                elif event_options['sun']['start'] == "set":
                  e_start=set_time.timestamp()
                else:
                  logging.error('Sunrise start time option is incorrect, valid options are "rise" or "set"')
                if event_options.has_option('sun','start_offset'):
                  try: # add start offset
                    e_start=e_start+(float(event_options['sun']['start_offset'])*60) # sunrise + offset
                  except:
                    logging.error('Sunrise start offset format is incorrect! Format is "start_offset : 999"')
            if event_options.has_section('sun'):
              if event_options.has_option('sun','end'):
                if event_options['sun']['end'] == "rise":
                  e_end=rise_time.timestamp()
                elif event_options['sun']['end'] == "set":
                  e_end=set_time.timestamp()
                else:
                  logging.error('Sunrise end time option is incorrect, valid options are "rise" or "set"')
                if event_options.has_option('sun','end_offset'):
                  try: # add end offset
                    e_end=e_end+(float(event_options['sun']['end_offset'])*60) # sunset + offset  
                  except:
                    logging.error('Sunset end offset format is incorrect! Format is "end_offset : 999"')
            if s_start:
                logging.debug('Switch on %s at %s %+.1f min',e.location.value,e_start_dt.strftime('%Y-%m-%d %H:%M:%S'),r_time_1/60)
                try:
                  switch_type[config[e.location.value]['type']](e.location.value,True,e_start+r_time_1)
                except:
                  logging.critical('Error: %s at %s + %s',e.summary.value,e_start,r_time_1,'!')
            if s_end:
                logging.debug('Switch off %s at %s %+.1f min',e.location.value, e_end_dt.strftime('%Y-%m-%d %H:%M:%S'),r_time_2/60)
                try:
                  switch_type[config[e.location.value]['type']](e.location.value,False,e_end+r_time_2)
                except:
                  logging.critical('Error for %s at %s+ %s',e.summary.value,e_end,r_time_2)

      logging.debug('Scheduler queue:\n%s',s.queue)
      logging.info('Start scheduler at %s',time.strftime('%Y-%m-%d %H:%M:%S'))
      s.run()
      logging.info('<><><> Completed scheduled events for this time interval. <><><>')

    else:
      logging.info('<><> No calendar events in this time interval. <><>')
  

if __name__ == '__main__':
    main()
