#!/usr/bin/python

import os
import shutil
import subprocess
import re
import json
import string

import random

# LOAD CUSTOM CONFIGURATION
import yaml
from Config import Config
with open(".env.yml", "r") as env:
  cfg = Config(yaml.load(env.read()))
# LOAD CUSTOM CONFIGURATION

import requests
import git
import boto3

# Create SQS client
sqs = boto3.client('sqs'
        ,region_name=cfg.get('aws.sqs.region')
        ,aws_access_key_id=cfg.get('aws.access_key')
        ,aws_secret_access_key=cfg.get('aws.secret_key')
    )

queue_url = cfg.get('aws.sqs.url')

# Methods for processing a message from the queue
def get_message():
    return sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        MessageAttributeNames=[
            'All'
        ],
        VisibilityTimeout=60
    )['Messages'][0]

def delete_message(message):
    # Delete received message from queue
    receipt_handle = message['ReceiptHandle']
    sqs.delete_message(
        QueueUrl=queue_url,
        ReceiptHandle=receipt_handle
    )
    print('Received and deleted message: %s' % message)

#############################################
# CONFIGURATION
PROJECT_DIRECTORY = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
SUBMISSION_DIRECTORY = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
SUREFIRE_REPORTS_DIRECTORY = "{}/target/surefire-reports".format(SUBMISSION_DIRECTORY)

def main():
    #############################################
    # MAKE A FRESH project FOLDER WITH NO CONTENT
    if os.path.exists(PROJECT_DIRECTORY):
        shutil.rmtree(PROJECT_DIRECTORY)
    os.mkdir(PROJECT_DIRECTORY)
    #############################################

    # Obtain a message from the queue. Once this method is run
    # the script will have 30 minutes to process this lab
    message = get_message()
    message_body = json.loads(message['Body'])

    #############################################
    # MAIN SCRIPT
    git.Repo.clone_from(message_body['assessment']['url'], PROJECT_DIRECTORY)
    git.Repo.clone_from(message_body['submission']['submission_url'], SUBMISSION_DIRECTORY)

    shutil.rmtree("{}/src/test".format(SUBMISSION_DIRECTORY))
    shutil.copytree("{}/src/test".format(PROJECT_DIRECTORY), "{}/src/test".format(SUBMISSION_DIRECTORY))

    subprocess.run(["mvn", "-f", "{}/{}/pom.xml".format(SCRIPT_PATH, SUBMISSION_DIRECTORY), "test"])

    results = {}

    tests_ran_pattern = re.compile(r'run:\s+(\d+)')
    tests_failed_pattern = re.compile(r'Failures:\s+(\d+)')
    tests_errors_pattern = re.compile(r'Errors:\s+(\d+)')
    tests_skipped_pattern = re.compile(r'Skipped:\s+(\d+)')

    for filename in os.listdir(SUREFIRE_REPORTS_DIRECTORY):
        if filename.endswith(".txt"):
            with open(os.path.join(SUREFIRE_REPORTS_DIRECTORY, filename), "r") as report:
                report_stats = report.readlines()[3]
                ran = int(tests_ran_pattern.findall(report_stats)[0])
                failed = int(tests_failed_pattern.findall(report_stats)[0])
                errors = int(tests_errors_pattern.findall(report_stats)[0])
                skipped = int(tests_skipped_pattern.findall(report_stats)[0])
                overall = ran - errors - failed - skipped

                results[filename.replace(".txt", "")] = {"ran": ran, "failed": failed, "errors": errors, "skipped": skipped, "overall": overall}

    total_tests = 0
    total_passes = 0
    for test in results.values():
        total_tests = total_tests + test["ran"]
        total_passes = total_passes + test["overall"]

    results["total_tests"] = total_tests
    results["total_passes"] = total_passes
    results["grade"] =  "{}%".format(str(total_passes / total_tests * 100)[:5])

    submission_endpoint = "{}/submissions/{}".format(cfg.get('zipcode.portal.url'), str(message_body['submission']['id']))
    data = {"grade": total_passes}
    headers = {"Authorization": "Bearer {}".format(cfg.get('zipcode.portal.token'))}

    response = requests.put(submission_endpoint, params=data, headers=headers, verify=False)

    response.raise_for_status

    delete_message(message)
    
    #############################################

    #############################################
    # CLEANUP
    shutil.rmtree(PROJECT_DIRECTORY)
    shutil.rmtree(SUBMISSION_DIRECTORY)
    #############################################

if __name__ == "__main__":
    main()