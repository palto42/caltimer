#! /usr/bin/python3
import serial
import argparse

parser = argparse.ArgumentParser()

#parser.add_option('-d', '--data',
#    help="data to be sent on serial port", default="V")

parser.add_argument("data")

args = parser.parse_args()

print ("sende:",args.data)

#port = "/dev/ttyUSB.FTDI"
port = "/dev/ttyUSB.Nano"

ser = serial.Serial(port, 38400)
x = ser.write(args.data.encode()+b'\n')
ser.close()

