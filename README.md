# scheduler - caldav based timer on Raspbeey Pi
The idea of this project is to control different power switches via web-calender entries. 
I'm using Nextcloud to host the calendar, but any other server with a caldav interfce should work.

Supported switched:
* RC power plugs via 433 MHz transmitter (connected to Raspberry Pi GPIO)
* Switch conencted directly to a GPIO port
* Pulsed switch connected directly to the GPIO port
  * Can be used to emulate the power button of another device (I use it for my NAS)

## Config file
The Python script uses an ini file to define the available swithce and some general settings.

## Timer entries
For each switch time a calendar entry is added with an aritrary summary, the location containing teh switch name 
(as per ini file) and an optional description with extra settings. 
The start and end time of the calendar entry are simply the on and off time for the switch.

## Dependencies
Some extra Python libraries used are.
* caldav https://pypi.python.org/pypi/caldav
  * https://github.com/python-caldav/caldav
  * Install with pip3 caldav
* sunrise_sunset library
  * https://github.com/jebeaudet/SunriseSunsetCalculator
  * sudo pip3 install git+https://github.com/palto42/SunriseSunsetCalculator.git 

On Raspbian Jessie I installed pip3 for Python3, which required some extra libraries first:
* Install
  * sudo apt-get install libxml2-dev libxslt1-dev 
* Install pip3
  * sudo apt-get install python3-pip 

## RC transmitter
There are several web pages decribing how to use a cheap RC433 transmitter on Raspberry Pi.
I'm using the library https://github.com/ninjablocks/433Utils since this was the only one which worked with my ZAP switches.
Unfortunately this library onyl provides a binary an not python code, but the main thing is that it works well ;-)
