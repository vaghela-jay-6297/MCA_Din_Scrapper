import requests
import xml.etree.ElementTree as ET
import json
import csv
from django.core.mail import EmailMessage
import os
from django.conf import settings
import time
import random

PARAMETERS = [
    "addCorrregofc", "adhaar", "amountSecured", "amountSecuredWords", "areaOfoccu",
    "artentRenched", "authorizedCapital", "categoryCompany", "cityOne", "classCompany",
    "cntryCode", "companyAddress", "companyOrg1", "companyType", "country", "crDat",
    "creationDate", "dateOfBirth", "descriptionOne", "durationMonth", "durationYear",
    "educationQual", "email", "familyName", "fatherFirstName", "fatherLastName",
    "fatherMiddleName", "fatherName", "firstName", "flag", "flagOne", "flagTwo",
    "havingShareCapital", "houseNum", "iso", "middleName", "modifyDate", "nameChrgHolder",
    "nameL", "nameOrgOne", "namePerson", "nameROC", "nationality", "nomidProof",
    "nomresProof", "paFax", "paPhone", "paState", "paddressLineOne", "paddressLineTwo",
    "pan", "passport", "permanantAdd", "personName", "placeOfBirth", "postCodeOne",
    "presentAdd", "presentAddCity", "presentAddCountry", "presentAddFax",
    "presentAddLineOne", "presentAddLineTwo", "presentAddPhone", "presentAddPincode",
    "presentAddState", "rbAddress", "rbFatherName", "rbGender", "region",
    "residentialAddr", "rigistarOffice", "satisfyDate", "state1", "statePropComp",
    "street", "stringOut1", "subCatCompany", "surName", "typeCompany", "voteridCrd",
    "pMobile"
]

def validate_din_range(start, end):
    if start > end:
        return False, "Start range must be less than or equal to end range"
    return True, ""

def validate_din_csv(file_path):
    try:
        if not os.path.exists(file_path):
            return False, f"CSV file not found at {file_path}", []
        
        din_numbers = []
        with open(file_path, mode='r', newline='', encoding='utf-8') as file:
            reader = csv.reader(file)
            header = next(reader, None)  # Check for header
            if header and len(header) > 1:
                return False, "CSV file must contain only one column with DIN numbers", []
            
            for row in reader:
                if not row:
                    continue
                if len(row) != 1:
                    return False, f"Invalid row in CSV: {row} (must contain exactly one DIN)", []
                din = row[0].strip()
                if not din.isdigit():
                    return False, f"Invalid DIN number in CSV: {din} (must be a positive integer)", []
                din_numbers.append(din)
        
        if not din_numbers:
            return False, "CSV file is empty or contains no valid DIN numbers", []
        
        return True, "", din_numbers
    except Exception as e:
        return False, f"Error reading CSV file: {str(e)}", []

def generate_din_csv(file_path, start_range, end_range):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            for din in range(start_range, end_range + 1):
                writer.writerow([f"{din:08d}"])
        return True
    except Exception:
        return False

def xml_to_json(xml_string):
    try:
        root = ET.fromstring(xml_string)
        def parse_element(element):
            parsed_data = {}
            for child in element:
                if len(child):
                    parsed_data[child.tag] = parse_element(child)
                else:
                    parsed_data[child.tag] = child.text
            return parsed_data
        return json.dumps(parse_element(root), indent=4)
    except Exception:
        return "{}"

def read_din_numbers_from_csv(file_path):
    try:
        din_numbers = []
        with open(file_path, mode='r', newline='') as file:
            reader = csv.reader(file)
            for row in reader:
                if row:
                    din_numbers.append(row[0])
        return din_numbers
    except Exception:
        return []

def find_key_value(data, key):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for k, v in data.items():
            result = find_key_value(v, key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_key_value(item, key)
            if result is not None:
                return result
    return None

def write_response_to_csv(file_path, din, response_json):
    try:
        response_data = json.loads(response_json)
        file_exists = os.path.isfile(file_path)
        with open(file_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["DIN"] + PARAMETERS)
            row_data = [din] + [find_key_value(response_data, param) for param in PARAMETERS]
            writer.writerow(row_data)
        return True
    except Exception:
        return False

def write_empty_response_to_csv(file_path, din):
    try:
        file_exists = os.path.isfile(file_path)
        with open(file_path, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if not file_exists:
                writer.writerow(["DIN"] + PARAMETERS)
            row_data = [din] + [""] * len(PARAMETERS)
            writer.writerow(row_data)
        return True
    except Exception:
        return False

def send_post_request(din, output_file, max_retries=3, retry_delay=2):
    for attempt in range(max_retries + 1):
        try:
            url = "http://www.mca.gov.in/FOServicesWeb/NCAPrefillService"
            headers = {
                "Accept": "*/*",
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "",
                "User-Agent": "Mozilla/3.0 (compatible; Spider 1.0; Windows)",
                "Host": "www.mca.gov.in",
                "Connection": "Keep-Alive",
                "Cache-Control": "no-cache"
            }
            xml_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
            <soap:Envelope
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xmlns:xsd="http://www.w3.org/2001/XMLSchema"
                xmlns:SOAP-ENC="http://schemas.xmlsoap.org/soap/encoding/"
                xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
                <soap:Body>
                    <tns:getNCAPrefillDetails
                        xmlns:tns="http://ncaprifill.org/wsdl">
                        <NCAPrefillProcessorDTO>
                            <callID>DIN</callID>
                            <din>{din}</din>
                            <formID>ZI03</formID>
                            <sid>NCA</sid>
                        </NCAPrefillProcessorDTO>
                    </tns:getNCAPrefillDetails>
                </soap:Body>
            </soap:Envelope>"""
            response = requests.post(url, headers=headers, data=xml_payload, timeout=30)
            if response.status_code == 200:
                json_response = xml_to_json(response.text)
                write_response_to_csv(output_file, din, json_response)
                return True
            elif response.status_code >= 500:
                if attempt < max_retries:
                    sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(sleep_time)
                else:
                    write_empty_response_to_csv(output_file, din)
                    return False
            else:
                write_empty_response_to_csv(output_file, din)
                return False
        except requests.exceptions.RequestException:
            if attempt < max_retries:
                sleep_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_time)
            else:
                write_empty_response_to_csv(output_file, din)
                return False
    return False

def process_din_csv(input_csv, output_csv):
    try:
        din_numbers = read_din_numbers_from_csv(input_csv)
        success_count = 0
        total_count = len(din_numbers)
        for i, din in enumerate(din_numbers):
            if send_post_request(din, output_csv, max_retries=3, retry_delay=2):
                success_count += 1
            time.sleep(0.5)
        return success_count, total_count
    except Exception:
        return 0, 0