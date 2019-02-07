#! /usr/bin/env python

# Reseller Automated Migration Tool
# Copyright (C) 2019 BronzeEagle

# This file is part of Reseller Automated Migration Tool.

# Reseller Automated Migration Tool is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Reseller Automated Migration Tool is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Reseller Automated Migration Tool.  If not, see <http://www.gnu.org/licenses/>.

import json, time, os, random, getpass, urllib.parse, urllib.request, datetime, sys
import http.cookiejar as cookielib

class Reseller:
    def __init__(self, hostname, username, password, ticket_id):
        self.hostname_port = '{}:2083'.format(hostname)
        self.hostname = hostname
        self.username = username
        self.password = password
        self.ticket_id = ticket_id

        # get environment stuff to save time
        self.env_user = os.environ['USER']

        # setup working directory for backup locations
        if not os.path.exists("/home/{}/automigrations/".format(self.env_user)):
            os.mkdir("/home/{}/automigrations/".format(self.env_user))

        self.working_directory = '/home/{}/automigrations/{}/'.format(self.env_user, self.ticket_id)
        if not os.path.exists(self.working_directory):
            os.mkdir(self.working_directory)

        # set dict for login data that'll be passed to urllib
        self.login_data = {
            'user': self.username,
            'pass': self.password,
            }

        # initialize cookielib
        self.cj = cookielib.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.data = urllib.parse.urlencode(self.login_data)

        # grab cpanel session id and then grab account list
        try:
            self.session_id = self.get_session()
            self.accounts = self.get_accounts()
            
        except urllib.error.URLError:
            print("Invalid hostname or login credential")
            sys.exit(1)

        # create array for backup files
        self.backup_files = []

        # generate and download each backup
        self.get_backups()

    # easier way to get the url n junk
    def get_url(self, url):
        return self.opener.open(url, self.data.encode('utf-8')).read().decode('utf-8')

    def get_session(self):
        url = 'https://{}/login/?login_only=1'.format(self.hostname_port)
        res = self.get_url(url)
        
        return json.loads(res)['security_token']

    # luckily most of this is json, so grab the dict and return
    def get_accounts(self):
        url = 'https://{}{}/execute/Resellers/list_accounts'.format(self.hostname_port, self.session_id)
        res = json.loads(self.get_url(url))
        accounts = []
        for u in res['data']:
            accounts.append(u['user'])
        return accounts

    def get_backups(self):
        # iterate over each user, generate a backup, wait for it to complete, and download it
        for user in self.accounts:
            cj = cookielib.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            login_data = urllib.parse.urlencode({'user' : user, 'pass' : self.password})
            resp = opener.open('https://{}/login/?login_only=1'.format(self.hostname_port), login_data.encode('utf-8'))
            session_id = json.loads(resp.read().decode('utf-8'))['security_token']

            # generate the backup
            opener.open('https://{}{}/frontend/paper_lantern/backup/wizard-dofullbackup.html'.format(self.hostname_port, session_id))

            # grab a list of all backups
            html = opener.open('https://{}{}/execute/Fileman/list_files?&types=file%7Cfile&include_mime=1&raw_mime_types=application/x-gzip'.format(self.hostname_port, session_id))

            backups = json.loads(html.read().decode('utf-8'))['data']

            file_list = []

            for backup in backups:
                file_list.append(backup['file'])

            # make sure it's a backup from today and this user
            if 'backup-' in file_list[-1] and '{}.tar.gz'.format(user) in file_list[-1]:
                check_inprog_bk = opener.open("https://{}{}/frontend/paper_lantern/backup/wizard-fullbackup.html".format(self.hostname_port, session_id))

                # make sure it's not still generating!
                while "inprogress" in check_inprog_bk.read().decode('utf-8'):
                    time.sleep(10)
                    check_inprog_bk = opener.open("https://{}{}/frontend/paper_lantern/backup/wizard-fullbackup.html".format(self.hostname_port, session_id))

                download_backup = opener.open("https://{}{}/download?file={}".format(self.hostname_port, session_id, file_list[-1]))

                # and finally download the backup!
                with open("{}{}".format(self.working_directory, file_list[-1]), 'wb') as output:
                    output.write(download_backup.read())
            else:
                print("There was an issue with the name of the backup file. I suggest a manual migration from here bud")
                sys.exit(1)

            # add the backup file to the list of total backup files
            self.backup_files.append("{}{}".format(self.working_directory, backup['file']))

            # gather facts
            vhost_info = json.loads(opener.open("https://{}{}/execute/LangPHP/php_get_vhost_versions".format(self.hostname_port, session_id)).read().decode('utf-8'))
            domain = vhost_info['data'][0]['vhost']
            php_version = vhost_info['data'][0]['version']

            inode_usage = json.loads(opener.open("https://{}{}/execute/Quota/get_quota_info".format(self.hostname_port, session_id)).read().decode('utf-8'))['data']['inodes_used']
            
            facts = {
                "username": user,
                "domain": domain,
                "php_version": php_version,
                "inode_usage": inode_usage,
            }

            print(facts)

if __name__ == "__main__":
    # gather reseller information
    hostname = input("Please provide the reseller server's hostname or IP: ")
    username = input("Please provide the reseller username: ")
    password = getpass.getpass("Please provide the reseller server's password: ")
    ticket_id = input("Please provide the ticket number: ")

    #begin
    print("\nGenerating server backups..")
    print("##########################################")
    print("#    Facts gathered during retrieval     #")
    print("##########################################")
    reseller = Reseller(hostname, username, password, ticket_id)

     #output each backup location for easy copy/paste for re-importing
    print("##########################################")
    print("# path to each backup file for importing #")
    for file in reseller.backup_files:
        print(file)
    print("##########################################")
