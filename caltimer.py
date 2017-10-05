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
logging.basicConfig(stream=sys.stderr, format='%(asctime)s caltimer.py: %(levelname)s : %(message)s', level=logging.INFO)


def rc_switch(switch,onoff,stime):
    if onoff:
      sendcode=config[switch]['oncode']
    else:
      sendcode=config[switch]['offcode']
    logging.info('<<< Schedule to send RC code %s at time %s',sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)))
    s.enterabs(stime,1,subprocess.call,
        argument=([config['DEFAULT']['rf433'],sendcode,
        config[switch]['protocol'],config[switch]['pulselength']],));

def rc_comag(switch,onoff,stime):
    # Comag code calculation:
    # switch 0 = binary "01"
    # switch 1 = binary "00"
    # ON       = binary "0001"
    # OFF      = binary "0100"
    #
    # Example:
    # Channel   Socket    ON/OFF
    # 0 1 0 0 0 0 0 1 1 0 ON
    if onoff:
      sendcode=config[switch]['oncode']
    else:
      sendcode=config[switch]['offcode']
    logging.info('<<< Schedule to send RC code %s at time %s',sendcode, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stime)))
    s.enterabs(stime,1,subprocess.call,
        argument=([config['DEFAULT']['rf433'],sendcode,
        config[switch]['protocol'],config[switch]['pulselength']],));

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
  'rc'    : rc_switch,
  'comag' : rc_comag,
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

  GPIO.setmode(GPIO.BCM)
  GPIO.setwarnings(False)

  # Timezone offset
  tzoffset = datetime.today().hour-datetime.utcnow().hour

  # Read ini file for RC switch definition
  # keys: oncode, offcode, protocol, pulselength
  # example: config['switchname']['oncode']
  global config
  config = configparser.ConfigParser()
  config.sections()
  config.read('/etc/caltimer/caltimer.ini')

  # set logfile
  try:
    # check if logfile is defined and can be opened for write/append
    logfile=open(config['LOGGING']['logfile'],'a')
    logfile.close()
    # Remove all handlers associated with the root logger object.
    for handler in logging.root.handlers[:]:
      logging.root.removeHandler(handler)
    # Reconfigure logging again, this time with a file.
    logging.basicConfig(filename = config['LOGGING']['logfile'], level=logging.INFO, format='%(asctime)s caltimer.py: %(levelname)s : %(message)s')
  except:
    logging.error('No (correct) filename defined, using sdterr for logging.')
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

    logging.info("Events between: %s and %s",dt,dt_end)

    results = calendar.date_search(
        dt - timedelta(hours=tzoffset), dt_end - timedelta(hours=tzoffset) )

    r_time_1 = 0
    r_time_2 = 0
    
    logging.info('%s events found for defined period.',len(results))
    if len(results)>0:
      # calculate sunrise and sunset
      ro = SunriseSunset(datetime.now(), latitude=float(config['CALENDAR']['latitude']),
          longitude=float(config['CALENDAR']['longitude']), localOffset=float(config['CALENDAR']['local_offset']))
      rise_time, set_time = ro.calculate()
      logging.info('Sunrise %s, sunset %s',rise_time, set_time)

      # schedule events
      logging.info('Define scheduler')
      global s
      s = sched.scheduler(time.time, time.sleep)
      for event in results:
        event.load()
        e = event.instance.vevent
        if not e.location.value in config:
          logging.error ('>>> Event "%s" at %s has an undefined RC-switch "%s", skipping this event.',
            e.summary.value, e.dtstart.value.strftime("%H:%M"), e.location.value)
        else:
          e_start = e.dtstart.value.timestamp()
          e_end = e.dtend.value.timestamp()
          # check if start/stop events are in current time interval
          s_start = e_start >= dt.timestamp() and e_start < dt_end.timestamp()
          s_end = e_end >= dt.timestamp() and e_end <= dt_end.timestamp()

          if s_start or s_end: # process event only if start or end is in current interval
            logging.info('>>> Schedule event: %s starting at %s <<<',e.summary.value,e.dtstart.value.strftime("%H:%M"))
            event_options = configparser.ConfigParser() # clear event options from previous event
            try:
              description = e.description.value
            except:
              logging.info('No description for this event')
              description = '[DEFAULT]' # define empyt description to clear previous
            try:
              event_options.read_string(description)
              logging.info('Description: %s',description)
            except:
              logging.warning('Description incorrect for this event, treating as empty (no options)')

            # logging event options at INFO level
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
                  switch_type[config[e.location.value]['type']](e.location.value,True,e_start+r_time_1)
                except:
                  logging.error('Error: %s at %s + %s',e.summary.value,e_start,r_time_1,'!')
            if s_end:
                logging.info('Switch off %s at %s %+.1f min',e.location.value, datetime.fromtimestamp(e_end).strftime('%H:%M:%S'),r_time_2/60)
                try:
                  switch_type[config[e.location.value]['type']](e.location.value,False,e_end+r_time_2)
                except:
                  logging.error('Error for %s at %s+ %s',e.summary.value,e_end,r_time_2)

      logging.debug('Scheduler queue:\n%s',s.queue)
      logging.info('Start scheduler at %s',time.strftime('%H:%M:%S'))
      s.run()
      logging.info('All scheduled events completed.')

    else:
      logging.info('No calendar events in this time interval.')
  

if __name__ == '__main__':
    main()
