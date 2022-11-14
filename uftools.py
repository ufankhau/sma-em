#!/usr/bin/python3
"""
*  ----------------------------------------------------------------------------
*  Set of auxiliary functions used in smaller and larger projects
*
*  print_line:	
*
*  2021-May-03
*  ---------------------------------------------------------------------------- 
"""
#  load necessary libraries
from colorama import init as colorama_init
from colorama import Fore, Back, Style
from time import localtime, strftime
from unidecode import unidecode
import sdnotify

#  systemd service notifications - https://github.com/bb4242/sdnotify
sd_notifier = sdnotify.SystemdNotifier()

#  -----------------------
#  logging function
#  -----------------------
def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True, sd_notify=False, logfile=False):
	timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
	if console:
		if error:
			print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + text + Style.RESET_ALL, file=sys.stderr)
		elif warning:
			print(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
		elif verbose:
			print(Fore.GREEN + '[{}] '.format(timestamp) + Fore.YELLOW + '- ' + '{}'.format(text) + Style.RESET_ALL)
		elif debug:
			print(Fore.CYAN + '[{}] '.format(timestamp) + '- (DBG): ' + '{}'.format(text) + Style.RESET_ALL)
		elif info:
			print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
			
	if logfile:
		if error:
			f.write(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + text + '\n' + Style.RESET_ALL, file=sys.stderr)
		elif warning:
			f.write(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + '\n' + Style.RESET_ALL)
		elif verbose:
			f.write(Fore.GREEN + '[{}] '.format(timestamp) + Fore.YELLOW + '- ' + '{}'.format(text) + '\n' + Style.RESET_ALL)
		elif debug:
			f.write(Fore.CYAN + '[{}] '.format(timestamp) + '- (DBG): ' + '{}'.format(text) + '\n' + Style.RESET_ALL)
		elif info:
			f.write(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + '\n' + Style.RESET_ALL)

	timestamp_sd = strftime('%b %d %H:%M:%S', localtime())
	if sd_notify:
		sd_notifier.notify('STATUS={} - {}.'.format(timestamp_sd, unidecode(text)))
