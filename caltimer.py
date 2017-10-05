#!/usr/bin/python3

#########################################################  
# Calernder based scheduler to switch RF433 sockets     #
# using cli codesend                                    #
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
# 2017-10-04                                            #
#########################################################

import configparser
import subprocess
from random import uniform
import sched, time
from datetime import datetime, date, timedelta
from sunrise_sunset import SunriseSunset
import caldav
from caldav.elements import dav, cdav
import RPi.GPIO as GPIO
import logging, sys

# set initial logging to stderr, level INFO
logging.basicConfig(stream=sys.stderr, format='%(asctime)s scheduler.py: %(levelname)s : %(message)s', level=logging.INFO)


def rc_switch(switch,onoff,stime):
    if onoff:
      sendcode=switches[switch]['oncode']
    else:
      sendcode=switches[switch]['offcode']
    logging.info('Schedule to send RC code %s at time %s',sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)))
    s.enterabs(stime,1,subprocess.call,
        argument=([switches['DEFAULT']['rf433'],sendcode,
        switches[switch]['protocol'],switches[switch]['pulselength']],));

def gpio_switch(switch,onoff,stime):
# Set the pin to output (just to be sure...)
    try:
      GPIO.setup(int(switches[switch]['pin']), GPIO.OUT)
    except:
      logging.error('GPIO setup error for pin %d',switches[switch]['pin'])
# Can directly use the Boolean variabe onoff since True=1=GPIO.HIGH
    s.enterabs(stime,1,GPIO.output,argument=(int(switches[switch]['pin']),onoff));
    logging.info ('GPIO %s %s at %s',switches[switch]['pin'],onoff,time.strftime('%H:%M:%S', time.localtime(stime)));

def gpio_pulse(switch,onoff,stime):
# Set the pin to output (just to be sure...)
    try:
      GPIO.setup(int(switches[switch]['pin']), GPIO.OUT)
    except:
      logging.error('GPIO setup error for pin %d',switches[switch]['pin'])
# Get the duration of the pulse
    if onoff:
      pulsetime=float(switches[switch]['on'])
    else:
      pulsetime=float(switches[switch]['off'])
# Chek for maximum pulse length, e.g. 10s (configured in switches.ini)
    if pulsetime>float(switches['DEFAULT']['max_pulse']):
      logging.error('The pulse duration of %s s is too long, setting to max= %s',pulsetime,switches['DEFAULT']['max_pulse']);
      pulsetime=float(switches['DEFAULT']['max_pulse']);
    s.enterabs(stime,1,GPIO.output,argument=(int(switches[switch]['pin']),1));
    s.enterabs(stime+pulsetime,1,GPIO.output,argument=(int(switches[switch]['pin']),0));

def dummy_switch(switch,onoff,stime):
    s.enterabs(stime,1,logging.warning,argument=('Dummy: %s',onoff));

# Switch command options
# usage: switch_type[type]()
switch_type = {
  'rc'    : rc_switch,
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

#switches = 0

#############################################################
# MAIN                                                      #
#############################################################
def main():

  GPIO.setmode(GPIO.BCM)
  GPIO.setwarnings(False)

  # Timezone offset
  tzoffset = datetime.today().hour-datetime.utcnow().hour

  # Read ini file for RC switch definition
  # keys: oncode, offcode, protocol, pulselength
  # example: switches['switchname']['oncode']
  global switches
  switches = configparser.ConfigParser()
  switches.sections()
  switches.read('/etc/caltimer/switches.ini')

  # set logfile
  try:
    # check if logfile is defined and can be opened for write/append
    logfile=open(switches['LOGGING']['logfile'],'a')
    logfile.close()
    # Remove all handlers associated with the root logger object.
    for handler in logging.root.handlers[:]:
      logging.root.removeHandler(handler)
    # Reconfigure logging again, this time with a file.
    logging.basicConfig(filename = switches['LOGGING']['logfile'], level=logging.INFO, format='%(asctime)s scheduler.py: %(levelname)s : %(message)s')
  except:
    logging.error('No (correct) filename defined, using sdterr for logging.')
  # set logging level if defined in switches.ini
  try:
    logging.info('Set loglevel: %s',switches['LOGGING']['loglevel'])
    logging.getLogger().setLevel(loglevel[switches['LOGGING']['loglevel']])
  except:
    logging.error('No loglevel defined, using ERROR')
    logging.getLogger().setLevel(logging.ERROR)
 
  # Caldav url
  try:
    url = switches['CALENDAR']['caldav']
  except:
    logging.error('Missing or incorrect ini file, please check /etc/caltimer/switches.ini')
    return
  # Scheduler intervall in Minuten
  interval = int(switches['CALENDAR']['interval'])
  # Maximum pulse length for GPIO pulses
  # max_pulse = float(switches['DEFAULT']['max_pulse'])

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
    calendar = next((c for c in calendars if c.name == switches['CALENDAR']['calname']), None)
    if calendar is  None:
      logging.error('Calendar %s not found.',switches['CALENDAR']['calname'])
      logging.error('Available calendars:')
      for calendar in calendars:
        logging.error('  %s ',calendar.name)
      return
    logging.info("Using calendar %s", calendar)

    dt = datetime.today()
    dt = dt + timedelta(minutes = interval - dt.minute % interval, seconds = -(dt.second % 60), microseconds = -(dt.microsecond % 1000000))
    dt_end = dt+timedelta(minutes=interval)

    logging.info("Events between: %s and %s",dt,dt_end)

    results = calendar.date_search(
        dt - timedelta(hours=tzoffset), dt_end - timedelta(hours=tzoffset) )

    r_time_1 = 0
    r_time_2 = 0
    
    logging.info('%s events found for defined period.',len(results))
    if len(results)>0:
        # calculate sunrise and sunset
        ro = SunriseSunset(datetime.now(), latitude=float(switches['CALENDAR']['latitude']),
            longitude=float(switches['CALENDAR']['longitude']), localOffset=float(switches['CALENDAR']['local_offset']))
        rise_time, set_time = ro.calculate()
        logging.info('Sunrise %s, sunset %s',rise_time, set_time)
        for event in results:
            event.load()
            e = event.instance.vevent
            logging.info('Start: %s, end: %s', e.dtstart.value.strftime("%H:%M"), e.dtend.value.strftime("%H:%M"))
            logging.info('Summary: %s, location: %s', e.summary.value, e.location.value);
            try: # description may not be available
              logging.info ('Description:\n%s', e.description.value)
            except:
              logging.info ('No description available.')
            if not e.location.value in switches:
              logging.error ('Undefined RC-switch %s',e.location.value)
            
    # schedule events
        logging.info('Define scheduler')
        global s
        s = sched.scheduler(time.time, time.sleep)
        for event in results:
            event.load()
            e = event.instance.vevent
            e_start = e.dtstart.value.timestamp()
            e_end = e.dtend.value.timestamp()
            # check if start/stop events are in current time interval
            s_start = e_start >= dt.timestamp() and e_start < dt_end.timestamp()
            s_end = e_end >= dt.timestamp() and e_end < dt_end.timestamp()

            try:
              event_options.read_string(e.description.value)
            except:
              logging.warning('Description undefined or incorrect for event %s at %s',e.summary.value,e.dtstart.value.strftime("%H:%M"))
              event_options.read_string('[DEFAULT]') # read dummy settings to clear data from previous event
# logging event options
            if  logging.getLogger().getEffectiveLevel() <= logging.INFO:
              logging.info('This event options have been found:')
              for each_section in event_options.sections():
                logging.info ('Section  %s :',each_section)
                for (each_key, each_val) in event_options.items(each_section):
                  logging.info ('  %s : %s',each_key,each_val)

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
                try: # add end offset
                  e_end=e_end+(float(event_options['sun']['end_offset'])*60) # sunset + offset  
                except:
                  logging.error('Sunset end offset format is incorrect! Format is "end_offset : 999"')
            if s_start:
                logging.info('Switch on %s at %s %+.1f min',e.location.value,datetime.fromtimestamp(e_start).strftime('%H:%M:%S'),r_time_1/60)
                try:
                  switch_type[switches[e.location.value]['type']](e.location.value,True,e_start+r_time_1)
                except:
                  logging.error('Error: %s at %s + %s',e.summary.value,e_start,r_time_1,'!')
            if s_end:
                logging.info('Switch off %s at %s %+.1f min',e.location.value, datetime.fromtimestamp(e_end).strftime('%H:%M:%S'),r_time_2/60)
                try:
                  switch_type[switches[e.location.value]['type']](e.location.value,False,e_end+r_time_2)
                except:
                  logging.error('Error for %s at %s+ %s',e.summary.value,e_end,r_time_2)
        logging.debug('Scheduler queue:\n%s',s.queue)
        logging.info('Start scheduler at %s',time.strftime('%H:%M:%S'))
        s.run()
        logging.info('All scheduled events completed.')
    else:
        logging.info('No switching events in this time interval.')
  

if __name__ == '__main__':
    main()
