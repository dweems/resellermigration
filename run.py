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

###########################################
## usage: python run.py
## requirements: chromedriver, selenium
###########################################

from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
import multiprocessing as mp
import json, time, os, random, getpass

class Reseller:
    def __init__(self, hostname, username, password, ticket_id):
        self.hostname_port = '{}:2082'.format(hostname)
        self.hostname = hostname
        self.username = username
        self.password = password
        self.ticket_id = ticket_id

        #create array to store generated backups with account info
        self.reseller_facts = []

        #get environment stuff to save time
        self.env_user = os.environ['USER']

        #setup working directory for backup locations
        self.working_directory = '/home/{}/automigrations/{}/'.format(self.env_user, self.ticket_id)
        if not os.path.exists(self.working_directory):
            os.mkdir(self.working_directory)

        #Set chromedriver options
        chrome_options = webdriver.ChromeOptions() 
        chrome_options.add_argument("--headless")
        chrome_options.add_argument('download.default_directory={}'.format(self.working_directory))
        chrome_options.add_argument('download.prompt_for_download=False')
        chrome_options.add_argument('download.directory_upgrade=True')
        chrome_options.add_argument('safebrowsing.disable_download_protection=True')

        chrome_webdriver_bin = os.popen("which chromedriver").read()[:-1]

        #initialize the webdriver
        self.driver = webdriver.Chrome(executable_path=os.path.abspath(chrome_webdriver_bin), options=chrome_options) 

        #begin migration
        self.generate_backups()

        #wait for all backups to finish downloading
        self.download_wait(self.working_directory)

        #when everything is done, close the driver
        self.driver.close()

    def get_accounts(self):
        #load login page and login
        self.driver.get("http://{}".format(self.hostname_port))

        #log into account
        login = self.driver.find_element_by_name("user")
        login.clear()
        login.send_keys(self.username)
        login = self.driver.find_element_by_name("pass")
        login.clear()
        login.send_keys(self.password)
        login.send_keys(Keys.RETURN)

        #can be slow to load so we just wait a few seconds(you'll see this periodically - same thing)
        time.sleep(3)

        #need to get the sesion ID for /every/ session 
        session_id = self.driver.current_url.split("/")[3]

        self.driver.get("http://{}/{}/execute/Resellers/list_accounts".format(self.hostname_port, session_id))

        #return json formatted user list
        return json.loads(self.driver.find_elements_by_tag_name('pre')[0].text)

    def generate_backups(self):
        #iterate over all accounts and generate and download backup
        for account in self.get_accounts()['data']:
            print("Logging into {}'s cPanel account...".format(account['user']))
            self.driver.get("http://{}".format(self.hostname_port))

            #login to each resold account
            login = self.driver.find_element_by_name("user")
            login.clear()
            login.send_keys(account['user'])
            login = self.driver.find_element_by_name("pass")
            login.clear()
            login.send_keys(self.password)
            login.send_keys(Keys.RETURN)
            time.sleep(3)

            session_id = self.driver.current_url.split("/")[3]

            self.driver.get("http://{}/{}/frontend/paper_lantern/backup/wizard-fullbackup.html".format(self.hostname_port, session_id))

            #get list of backups
            backup_list = self.driver.find_element_by_id("backupList")
            backups = backup_list.find_elements_by_tag_name("li")
            newest_backup = ""

            #make sure there are backups
            if len(backups) > 0:
                newest_backup = backups[len(backups)-1].text.split(" ")[0]

            #disable the send email on completion email
            backup = self.driver.find_element_by_id("email_radio_disabled").click()
            backup = self.driver.find_element_by_id("backup_submit").click()
            time.sleep(2)
            backup = self.driver.find_element_by_id("lnkReturn").click()

            print("Generating backup for {}".format(account['user']))

            #get updated backup list
            backup_list = self.driver.find_element_by_id("backupList")
            backups = backup_list.find_elements_by_tag_name("li")

            #wait for the backup to complete
            while "inprogress" in backups[len(backups)-1].text:
                time.sleep(4)
                self.driver.refresh()
                time.sleep(1)
                backup_list = self.driver.find_element_by_id("backupList")
                backups = backup_list.find_elements_by_tag_name("li")

            #update newest_backup
            if newest_backup is not backups[len(backups)-1].text.split(" ")[0]:
                newest_backup = backups[len(backups)-1].text.split(" ")[0]
            else:
                newest_backup = backups[len(backups)-1].text.split(" ")[0]

            print("Backup complete: {}".format(newest_backup))
            
            time.sleep(2)

            #workaround for downloads in headless mode
            self.driver.command_executor._commands["send_command"] = ("POST", '/session/$sessionId/chromium/send_command')

            params = {'cmd': 'Page.setDownloadBehavior', 'params': {'behavior': 'allow', 'downloadPath': self.working_directory}}
            command_result = self.driver.execute("send_command", params)

            #download backup to self.working_directory
            download_backup = self.driver.find_element_by_partial_link_text(newest_backup)
            download_backup.click()

            print("Downloading backup to local directory: {}".format(self.working_directory))

            #get PHP info
            self.driver.get("http://{}/{}/execute/LangPHP/php_get_vhost_versions".format(self.hostname_port, session_id))
            vhost_info = json.loads(self.driver.find_elements_by_tag_name('pre')[0].text)

            #get inode usage
            self.driver.get("http://{}/{}/execute/Quota/get_quota_info".format(self.hostname_port, session_id))
            inodes_used = json.loads(self.driver.find_elements_by_tag_name('pre')[0].text)

            #create dict for total output
            facts = {
                "user": account['user'],
                "domain": vhost_info['data'][0]['vhost'],
                "inode_usage": inodes_used['data']['inodes_used'],
                "php_version": vhost_info['data'][0]['version']
            }

            #add facts to reseller_facts array
            self.reseller_facts.append(facts)

    def download_wait(self, path_to_downloads):
        dl_wait = True
        while dl_wait:
            time.sleep(1)
            dl_wait = False
            for fname in os.listdir(path_to_downloads):
                if fname.endswith('.crdownload'):
                    print("Waiting for download to complete...")
                    dl_wait = True
            print("Downloads complete!")

if __name__ == "__main__":
    # gather reseller information
    print("Please provide the reseller server's hostname or IP: ", end='')
    hostname = input()
    print("Please provide the reseller username: ", end='')
    username = input()
    password = getpass.getpass("Please provide the reseller server's password: ")
    print("Please provide the ticket number: ", end='')
    ticket_id = input()

    #begin
    print("Generating server backups..")
    reseller = Reseller(hostname, username, password, ticket_id)

    #output reseller facts that were gathered during migrations
    for fact in reseller.reseller_facts:
        print(fact)

    #output master backup path
    print("##########################################")
    print("# path to the the master account backup  #")
    os.system("echo \"{}$(ls {} | grep {})\"".format(reseller.working_directory, reseller.working_directory, reseller.username))

    #output each backup location for easy copy/paste for re-importing
    print("##########################################")
    print("# path to each backup file for importing #")
    os.system("for i in $(ls {}); do echo {}$i; done | grep -v {}".format(reseller.working_directory, reseller.working_directory, reseller.username))