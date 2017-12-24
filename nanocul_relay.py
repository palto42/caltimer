#!/usr/bin/python3

#===============================================================================
# This script receives RF messages from Kopp transmitters at 868 MHzs 
# and send them to other low cost RF 433 Mhz receivers
# 
# Matthias Homann
# 21.12.2017
#  
#===============================================================================

import sys
import logging
import argparse
import configparser
import serial
from time import sleep
import time

import RPi.GPIO as GPIO
from rpi_rf import RFDevice

GPIO.setwarnings(False)

# constant definitions
pulse_comag = 350
pulse_zap = 187
kopp_time = '00100'

# set initial logging to stderr, level INFO
logging.basicConfig(
    stream=sys.stderr,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    level=logging.INFO)

#+ 01234567890123456789
#~ kr07C2AD1A30CC0F0328
#~ ||  ||||  ||    ++-------- Transmitter Code 2
#~ ||  ||||  ++-------------- Keycode
#~ ||  ++++------------------ Transmitter Code 1
#~ ++------------------------ kr wird von der culfw bei Empfang einer Kopp Botschaft als 


#===============================================================================
# WZ Lampe an:  kt104B130300100N
# WZ Lampe aus: kt004B130300100N
# 
# Springbrunnen an:  kt1031090300100N
# Springbrunnen aus: kt0031090300100N
# Tase 2 an   : ktB031090300100N
# Taste 2 aus : ktA031090300100N
#===============================================================================

# Serial port config moved to ini file
#port = "/dev/ttyUSB.Nano"
#ser = serial.Serial(port, 38400, timeout=0)


def rf_switch(switch, onoff):
    if onoff:
        sendcode = config[switch]['oncode']
    else:
        sendcode = config[switch]['offcode']
    logging.info('<<< rf_switch send RF code %s at via %s',
                 sendcode,
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        subprocess.call([config['DEFAULT']['rf433'], sendcode,
                         config[switch]['protocol'],
                         config[switch]['pulselength']],)
    elif config[switch]['rf_code'] == "rpi-rf":
        rfdevice.tx_code(int(sendcode), int(config[switch]['protocol']),
                         int(config[switch]['pulselength']))
    else:
        logging.error(
            'rf_switch undefined rf_code for switch %s, check ini file!',
            switch)


def rf_comag(switch, onoff):
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
    logging.info('<<< rf_comag send RF code %s via %s',
                 sendcode,
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        subprocess.call([config['DEFAULT']['rf433'],
                         str(sendcode), "1", str(pulse_comag)],)
    elif config[switch]['rf_code'] == "rpi-rf":
        rfdevice.tx_code(int(sendcode), 1, pulse_comag)
    else:
        logging.error(
            'rf_comag undefined rf_code for switch %s, check ini file!',
            switch)


def rf_zap(switch, onoff):
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
    logging.info('<<< rf_zap send RF code %s via %s',
                 sendcode,
                 config[switch]['rf_code'])
    if config[switch]['rf_code'] == "rf433":
        subprocess.call([config['DEFAULT']['rf433'],
                         str(sendcode), "1", str(pulse_zap)],)
    elif config[switch]['rf_code'] == "rpi-rf":
        rfdevice.tx_code(sendcode, 1, pulse_zap)
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

    sendcode='kt'
    if onoff:
        if config.has_option(switch, 'key_on'):
            sendcode += config[switch]['key_on']
        else:
            # calculate key_on from key_off by adding 0x10
            sendcode += format(int(config[switch]['key_off'],base=16)+16,'X')
    else:
        sendcode += config[switch]['key_off']
    sendcode += config[switch]['transmit_1'] + config[switch]['transmit_1'] + kopp_time + 'N'
    logging.info('<<< rf_kopp send code %s to nanocul', sendcode)
    x = ser.write((sencode+'\n').encode())
    ser.close()
    
def configure_logging(log_arg, update, file):
    loglevel = {
        'CRITICAL': 50,
        'ERROR':    40,
        'WARNING':  30,
        'INFO':     20,
        'DEBUG':    10,
        'NOTSET':    0
    }
    # check if logfile is defined and can be opened for read
    print(config['LOGGING']['nanocul_log'])
    try:
        logfile = open(config['LOGGING']['nanocul_log'], 'r')
        logfile.close()
        log_exists = True
        #-------------------------------------- print ('File exists',log_exists)
    except:
        log_exists = False
    # check if logfile is defined and can be opened for write/append
    try:
        logfile = open(config['LOGGING']['nanocul_log'], 'a')
        logfile.close()
        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        # Reconfigure logging again, this time with a file.
        logging.basicConfig(
            filename=config['LOGGING']['nanocul_log'],
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    except:
        if log_exists:
            temp_log = config['LOGGING']['nanocul_log'][:-4] \
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
            if update:
                config.set('LOGGING','loglevel',log_arg.upper())
                update_ini(file)
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
    
    # Comamnd line arguments
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-i', '--init',
                        help='specify path/filename of ini file to read from',
                        default='/etc/pyscript/nanocul.ini')
    parser.add_argument('-l', '--log',
                        help='set log level (overwrites ini file)\n'
                        '  Supported levels are: '
                        'CRITICAL, ERROR, WARNING, INFO, DEBUG')
    parser.add_argument('-u', '--update',
                        help='Update ini file (e.g. log level)',
                        action='store_true')
    args = parser.parse_args()
    
    # Read ini file for RC switch definition
    # keys: oncode, offcode, protocol, pulselength
    # example: config['switchname']['oncode']
    global config
    config = configparser.ConfigParser()
    #config.sections()
    config.read(args.init)
    if len(config) <= 1:
        print ("ERROR: The specified ini file doesn't exit!")
        return
    
    # set logfile destination and log level
    configure_logging(args.log, args.update, args.init)

    if config.has_option('DEFAULT', 'pulselength'):
        pulse_comag=int(config['DEFAULT']['pulselength'])
        logging.debug('Setting pulse_comag = %s',pulse_comag)
        
    if config.has_option('DEFAULT', 'zap_pulse'):
        pulse_zap=int(config['DEFAULT']['zap_pulse'])
        logging.debug('Setting pulse_zap = %s',pulse_zap)

    if config.has_option('DEFAULT', 'kopp_time'):
        kopp_time = config['DEFAULT']['kopp_time'].zfill(5)
        logging.debug('Setting kopp_time = %s',kopp_time)

    if config.has_option('DEFAULT', 'ser_port'):
        logging.debug('Create serial interface %s',config['DEFAULT']['ser_port'])
        global ser
        ser = serial.Serial(config['DEFAULT']['ser_port'], 38400, timeout=0)

    # Enable RF transmitter
    global rfdevice
    rfdevice = RFDevice(int(config['DEFAULT']['gpio']))
    rfdevice.enable_tx()
    
    relays=[]
    #receive_code=dict()
    on_code=dict()
    off_code=dict()
    for i in config.sections():
        if config.has_option(i, 'relay'):
            relays.append(i)
            off_code[(config[i]['transmit_1']+config[i]['transmit_2']+
                      config[i]['key_off']).encode()]=config[i]['relay'].split(',')
            if config.has_option(i, 'key_on'):
                on_code[(config[i]['transmit_1']+config[i]['transmit_2']+
                         config[i]['key_on']).encode()]=config[i]['relay'].split(',')
            else:
                # calculate key_on from key_off by adding 0x10
                key_on=format(int(config[i]['key_off'],base=16)+16,'X')
                on_code[(config[i]['transmit_1']+config[i]['transmit_2']+
                         key_on).encode()]=config[i]['relay'].split(',')
                print(key_on,config[i]['key_off'])
            #receive_code[i]=config[i]['transmit_1']+config[i]['transmit_2']
            #print(receive_code[i],on_code[i],off_code[i])
            logging.debug('Transmitter %s is relayed to %s',i,config[i]['relay'].split(','))
    logging.info('Relays found: %s',relays)
    logging.debug('ON:  %s', on_code)
    logging.debug('OFF: %s', off_code)
    
    logging.debug('Enable Kopp receive mode.')
    kr_enable=True
    while kr_enable: 
        x = ser.write(b'krS\n')
        sleep(0.2)
        data = ser.read(9999)
        if len(data) > 0:
            logging.debug('Received: %s',data)
            if data == b'krS-ReceiveStart\r\n':
                kr_enable=False
                logging.info('Kopp receive mode enabled!')

    logging.debug('Start to listen for receiver nanocul...')
    while True:
        data = ser.read(9999)
        if len(data) > 0:
            logging.debug('length: %s',len(data))
            #logging.debug('Got: %s', data.decode('utf-8')[0:-2]) # decode ascii or utf-8, strip last 2 char (cr lf)
            if len(data) == 22:
                transmitter = data[4:8] + data[16:18]
                keycode = data[10:12]
                rec_code=transmitter+keycode
                logging.debug('Transmitter: %s, Key %s', transmitter.decode(), keycode.decode())
                if rec_code in on_code:
                    logging.debug('ON: %s',on_code[rec_code])
                    for tx in on_code[rec_code]:
                        rf_zap(tx, True)
                        logging.info('Switch light %s ON',tx)
                if rec_code in off_code:
                    logging.debug('ON: %s',off_code[rec_code])
                    for tx in off_code[rec_code]:
                        rf_zap(tx, False)
                        logging.info('Switch light %s OFF',tx)
            else:
                logging.debug('Got: %s', data.decode()[0:-2]) # decode to string, strip last 2 char (cr lf)
    
        sleep(0.1) # check for new received code 10x per second
    
    logging.debug('Disable Kopp receive mode.')
    x = ser.write(b'krE\n')
    ser.close()

if __name__ == '__main__':
    main()