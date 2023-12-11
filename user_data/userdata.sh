#!/bin/bash 

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


#This userdata script for AWS IoT Greengrass v2 

#Here we are installing dependencies that we will need to validate what we have created ie 
#creating a component
#You will need to install and set up your AWS IoT Greengrass device manually by following the 
#instrcutions at the link below:
#https://docs.aws.amazon.com/greengrass/v2/developerguide/install-greengrass-core-v2.html

sudo yum install pip -y

sudo yum install git -y

#aws-greengrass-gdk-cli
python3 -m pip install -U git+https://github.com/aws-greengrass/aws-greengrass-gdk-cli.git@v1.4.0


