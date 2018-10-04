#!/usr/bin/python3
import serial
from time import sleep

#+ 01234567890123456789
#~ kr07C2AD1A30CC0F0328
#~ ||  ||||  ||    ++-------- Transmitter Code 2
#~ ||  ||||  ++-------------- Keycode
#~ ||  ++++------------------ Transmitter Code 1
#~ ++------------------------ kr wird von der culfw bei Empfang einer Kopp Botschaft als 

#port = "/dev/ttyUSB.FTDI"
#port = "/dev/ttyUSB.Nano"
port = "/dev/ttyAMA0"
ser = serial.Serial(port, 38400, timeout=0)

while True:
    data = ser.read(9999)
    if len(data) > 0:
        #print ('length:',len(data))
        #print ('Got:', data.decode('utf-8')[0:-2]) # decode ascii or utf-8, strip last 2 char (cr lf)
        if len(data) == 22:
            transmitter = data.decode('utf-8')[4:8] + data.decode('utf-8')[16:18]
            keycode = data.decode('utf-8')[10:12]
            print ('Transmitter:',transmitter,' Key:',keycode)
        else:
            print ('Got:', data.decode('utf-8')[0:-2]) # decode ascii or utf-8, strip last 2 char (cr lf)

    sleep(0.2)
    #print ('not blocked')

ser.close()
