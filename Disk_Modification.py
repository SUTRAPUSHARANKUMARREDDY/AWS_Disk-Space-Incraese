import boto3
import time
import json
import requests


# Plans and its max disk limit 
plans = {
    'medium': 45, #GB
    'large': 65, #GB
    'xlarge': 300, #GB
    '2xlarge': 400, #GB
}

# Customer list
customer_list = {
    'sharan': 'large',
    'test': 'large',
    # add more customers here...
}


# Slack webhook URL
slack_webhook_url = "https://hooks.slack.com/services/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"

def send_slack_message(slack_webhook_url, slack_message):
  print('>send_slack_message:slack_message:'+slack_message)
  slack_payload = {'text': slack_message}
  print('>send_slack_message:posting message to slack channel')
  response = requests.post(slack_webhook_url, json.dumps(slack_payload))
  response_json = response.text  # convert to json for easy handling
  print('>send_slack_message:response after posting to slack:'+str(response_json))

def lambda_handler(event, context):
    ec2_resource = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')
    ssm_client = boto3.client('ssm')
    
    send_message_to_slack = 0
    notification_message = 'Vomule is increased sucessfully \n'

    sns_message = json.loads(event['Records'][0]['Sns']['Message'])
    print(f"SNS message: {sns_message}")

    alarm_name = sns_message['AlarmName']
    _, instance_id, original_volume_id = alarm_name.split('_')

    instance = ec2_resource.Instance(instance_id)
    volumes = list(instance.volumes.all())


    # Get the 'org' tag of the instance
    org_tags = [t['Value'] for t in instance.tags if t['Key'] == 'org']

    if not org_tags:  # If the list is empty
        error_message = f"Instance {instance_id} does not have an 'org' tag."
        print(error_message)
        send_slack_message(slack_webhook_url, error_message)
        return {
            'statusCode': 400,
            'body': error_message
        }

    org = org_tags[0]
    

    if org not in customer_list:
        error_message = f"Instance {instance_id} does not belong to a customer."
        print(error_message)
        send_slack_message(slack_webhook_url, error_message)
        return {
            'statusCode': 400,
            'body': 'Instance does not belong to a customer'
        }
    info = 'Org = ' + org + '\n'
    info = info + 'InstanceId = ' + instance_id + '\n'
    info = info + 'VolumeID = ' + original_volume_id + '\n'
    
    
    customer_plan = customer_list[org]
    max_disk_size = plans[customer_plan]

    total_disk_size = sum([v.size for v in volumes])

    if total_disk_size >= max_disk_size:
        error_message = f"Max disk size reached for instance {instance_id} according to {customer_plan} plan"
        print(error_message)
        send_slack_message(slack_webhook_url, error_message)
        return {
            'statusCode': 200,
            'body': f"Max disk size reached according to {customer_plan} plan"
        }



    if len(volumes) == 1:
        
        send_message_to_slack = 1
        
        # Single volume script
        volume = volumes[0]
        original_volume_id = volume.id
        volume_id_without_hyphen = volume.id.replace("-", "")
        current_size = volume.size

        print(f"Instance ID: {instance_id}, Volume ID: {original_volume_id}")

        # Get the device name of the EBS volume
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    'lsblk | grep " disk" | awk \'{print $1}\''
                ]
            }
        )
        
        # Wait for the command to finish
        time.sleep(5)

        # Get the command ID
        command_id = response['Command']['CommandId']

        # Get the output of the command
        output = ssm_client.get_command_invocation(
          CommandId=command_id,
          InstanceId=instance_id,
        )

        print(f"Output from 'lsblk': {output['StandardOutputContent']}")

        # Parse the device name from the output
        device_name = "/dev/" + output['StandardOutputContent'].strip()

        # Increase disk size by 2GB
        new_size = current_size + 2
        response = ec2_client.modify_volume(VolumeId=original_volume_id, Size=new_size)
        print(f"Response from modify_volume: {response}")
        
        info = info + 'New Size = ' + str(new_size) + '\n'


        # Allow some time for the modify_volume operation to finish
        time.sleep(300)

        # Resize the partition
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    'sudo growpart ' + device_name + ' 1'
                ]
            }
        )

        # Allow some time for the growpart operation to finish
        time.sleep(10)
        
        # Get the file system
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    'df -Th | grep "^/dev" | awk \'{print $2}\''
                ]
            }
        )

        time.sleep(5)
        file_system = response['Command']['CommandId']
        output = ssm_client.get_command_invocation(
          CommandId=file_system,
          InstanceId=instance_id,
        )

        file_system_type = output['StandardOutputContent'].strip()
        print(f"File system type: {file_system_type}")

        # Decide which growfs command to run
        growfs_command = ""
        if file_system_type == "xfs":
            growfs_command = 'sudo xfs_growfs -d /'
        elif file_system_type in ["ext3", "ext4"]:
            growfs_command = 'sudo resize2fs ' + device_name
        else:
            raise Exception(f"Unsupported file system type: {file_system_type}")

        # Resize the file system
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    growfs_command
                ]
            }
        )

        # Wait for the command to finish
        time.sleep(10)
        
        notification_message += info + '\n'
        
        print("Successfully increased disk size")

        if send_message_to_slack == 1:
          print("slck msg final", notification_message)
          send_slack_message(slack_webhook_url, notification_message)
        else:
          print("Slack Message is not sent")

        return {
            'statusCode': 200,
            'body': 'Successfully increased disk size'
        }
        
    else:
        
        send_message_to_slack = 1
        
        # More than one volume script
        volume = ec2_resource.Volume(original_volume_id)
        if volume is None:
            raise Exception(f"No volumes found for instance {instance_id}")

        volume_id_without_hyphen = original_volume_id.replace("-", "")
        current_size = volume.size
        print(f"Instance ID: {instance_id}, Volume ID: {original_volume_id}")

        device_name = None
        for attachment in instance.block_device_mappings:
            if attachment['Ebs']['VolumeId'] == original_volume_id:
                device_name = attachment['DeviceName']
                break

        if device_name is None:
            raise Exception(f"No device found for volume {original_volume_id}")

        print(f"Device Name: {device_name}")

        new_size = current_size + 2
        response = ec2_client.modify_volume(VolumeId=original_volume_id, Size=new_size)
        print(f"Response from modify_volume: {response}")
        
        info = info + 'New Size = ' + str(new_size) + '\n'


        time.sleep(300)
        print("Volume is now 'in-use' and modification is 'completed'")

        # Identify file system type
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    f"df -T {device_name} | awk 'NR==2 {{print $2}}'"
                ]
            }
        )

        # Get the command ID
        command_id = response['Command']['CommandId']

        # Wait for the command to finish executing (this is just a placeholder, you may need to wait longer)
        time.sleep(60)

        # Get the command output
        output_response = ssm_client.get_command_invocation(
            CommandId=command_id,
            InstanceId=instance_id,
        )

        filesystem_type = output_response['StandardOutputContent'].strip()
        print(f"File System Type: {filesystem_type}")

        # Increase partition size
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={
                'commands': [
                    f'sudo growpart {device_name} 1'
                ]
            }
        )
        time.sleep(10)

        # Increase filesystem size
        if filesystem_type == 'xfs':
            response = ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': [
                        f'sudo xfs_growfs {device_name}'
                    ]
                }
            )
        elif filesystem_type == 'ext3' or filesystem_type == 'ext4':
            response = ssm_client.send_command(
                InstanceIds=[instance_id],
                DocumentName='AWS-RunShellScript',
                Parameters={
                    'commands': [
                        f'sudo resize2fs {device_name}'
                    ]
                }
            )
        else:
            return {
                'statusCode': 400,
                'body': f'Unexpected file system type: {filesystem_type}'
            }

        time.sleep(10)
        
        notification_message += info + '\n'

        print("Successfully increased disk size")
    
        if send_message_to_slack == 1:
          print("slck msg final", notification_message)
          send_slack_message(slack_webhook_url, notification_message)
        else:
          print("Slack Message is not sent")

        return {
            'statusCode': 200,
            'body': 'Successfully increased disk size'
        }
