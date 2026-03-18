"""Test file for basic SmartHub Location functionality."""
import pytest
from custom_components.smarthub import async_setup_entry
from custom_components.smarthub.api import SmartHubAPI, SmartHubLocation
from custom_components.smarthub.const import ELECTRIC_SERVICE

@pytest.fixture
def api_instance():
    """Create an API instance for testing."""
    return SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

def test_parse_locations(api_instance):
    """Test parsing location description."""
    test_data = [
      { # INACTIVE
        'customer': 'XXXXXXXX', 'customerName': 'CUSTOMER_NAME', 'additionalCustomerName': 'ADDITIONAL_CUSTOMER_NAME', 'account': 'ACCOUNT', 'address': 'ADDRESS, CITY, STATE ZIP_CODE', 'email': 'USER_ID', 'inactive': True, 'primaryServiceLocationId': 'LOCATION_ID',
        'serviceLocationIdToServiceLocationSummary': {
        'LOCATION_ID': {
           'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'meterNumbersToExternalMeterBaseIds': {'350017381': 'LOCATION_ID+1'},
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        },
       'serviceLocationToUserDataServiceLocationSummaries': {
         'LOCATION_ID': [
           {'services': ['ELEC'], 'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        ]},
        'serviceLocationToIndustries': {'LOCATION_ID': ['ELECTRIC']},
        'providerToDescription': {'NOVEC': 'NOVEC Electric Service'}, 'providerToProviderDescription': {'NOVEC': 'NOVEC Electric Service'},
        'serviceToServiceDescription': {'ELEC': 'Electric Service'},
        'serviceToProviders': {'ELEC': ['NOVEC']}, 'serviceLocationToProviders': {"LOCATION_ID": ['NOVEC']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'NOVEC Electric Service', 'services': ['ELEC']
      },
      {
        'customer': 'XXXXXXXX', 'customerName': 'CUSTOMER_NAME', 'additionalCustomerName': 'ADDITIONAL_CUSTOMER_NAME', 'account': 'ACCOUNT', 'address': 'ADDRESS, CITY, STATE ZIP_CODE', 'email': 'USER_ID', 'inactive': False, 'primaryServiceLocationId': 'LOCATION_ID',
        'serviceLocationIdToServiceLocationSummary': {
        'LOCATION_ID': {
           'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'meterNumbersToExternalMeterBaseIds': {'350017381': 'LOCATION_ID+1'},
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        },
       'serviceLocationToUserDataServiceLocationSummaries': {
         'LOCATION_ID': [
           {'services': ['ELEC'], 'id': {'srvLocNbr': "LOCATION_ID", 'serviceLocation': 'LOCATION_ID'},
           'location': 'YYYYYY',
           'address': {'addr1': 'ADDRESS', 'city': 'CITY', 'state': 'STATE', 'zip': 'ZIP_CODE'},
           'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765774800000, 'lastBillPresReadDtTm': 1768453200000,
           'activeRateSchedules': ['1ARC:NOVEC', '1ARG:NOVEC', '1ARN:NOVEC']}
        ]},
        'serviceLocationToIndustries': {'LOCATION_ID': ['ELECTRIC']},
        'providerToDescription': {'NOVEC': 'NOVEC Electric Service'}, 'providerToProviderDescription': {'NOVEC': 'NOVEC Electric Service'},
        'serviceToServiceDescription': {'ELEC': 'Electric Service'},
        'serviceToProviders': {'ELEC': ['NOVEC']}, 'serviceLocationToProviders': {"LOCATION_ID": ['NOVEC']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'NOVEC Electric Service', 'services': ['ELEC']
      },
      {
        'customer': 'XXXXXX1', 'customerName': 'CUSTOMER2', 'additionalCustomerName': 'CUSTOMER2 DISPLAY NAME', 'account': 'ACCOUNT1', 'address': 'ADDRESS, CITY, STATE ZIP_CODE', 'email': 'USER_ID', 'inactive': False, 'primaryServiceLocationId': 'LOCATION_ID2',
        'serviceLocationIdToServiceLocationSummary': {
          'LOCATION_ID2': {
            'id': {'srvLocNbr': 'LOCATION_ID2', 'serviceLocation': 'LOCATION_ID2'},
            'location': 'LOCATION_ID2b',
            'description': 'NICKNAME',
            'address': {'addr1': 'XXXXXX', 'city': 'YYYY', 'state': 'ZZZZ', 'zip': 'RRRRR', 'description': 'NICKNAME'},
            'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765688400000, 'lastBillPresReadDtTm': 1768366800000,
            'meterNumbersToExternalMeterBaseIds': {'LOCATION_ID2?': 'LOCATION_ID2+1'},
            'activeRateSchedules': ['RES01:1ELEC']
            }
         },
        'serviceLocationToUserDataServiceLocationSummaries': {
          'LOCATION_ID2': [
            {'services': ['ELEC'], 'id': {'srvLocNbr': 'LOCATION_ID2', 'serviceLocation': 'LOCATION_ID2'}, 'location': 'LOCATION_ID2b', 'description': 'NICKNAME',
             'address': {'addr1': 'XXXXXX', 'city': 'YYYY', 'state': 'ZZZZ', 'zip': 'RRRRR', 'description': 'NICKNAME'}, 'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1765688400000, 'lastBillPresReadDtTm': 1768366800000,
             'activeRateSchedules': ['RES01:1ELEC']
            }]
         },
        'serviceLocationToIndustries': {'LOCATION_ID2': ['ELECTRIC']},
        'providerToDescription': {'1ELEC': 'Electric Service'}, 'providerToProviderDescription': {'1ELEC': 'Electric Service'},
        'serviceToServiceDescription': {'ELEC': 'Electric Service'},
        'serviceToProviders': {'ELEC': ['1ELEC']}, 'serviceLocationToProviders': {'LOCATION_ID2': ['1ELEC']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'Electric Service', 'services': ['ELEC']
      },
      {
          "customer": "********", "customerName": "****** * *****", "additionalCustomerName": "********* * *****", "account": "*********", "address": "*** ******* ****** ** *, ****, ** *****", "email": "***.*****@**.***", "inactive": False, "primaryServiceLocationId": "*******",
          "serviceLocationIdToServiceLocationSummary": {
            "*******": {
              "id": {"srvLocNbr": "*******", "serviceLocation": "*******" },
              "location": "**********",
              "address": { "addr1": "*** ******* ****** ** *", "city": "****", "state": "**", "zip": "*****"},
              "serviceStatus": "ACTIVE", "lastBillPrevReadDtTm": 1766124000000, "lastBillPresReadDtTm": 1768802400000,
              "meterNumbersToExternalMeterBaseIds": { "*******": "*******+1"},
              "activeRateSchedules": [ "RES1:TCEC"]
            }
          },
          "serviceLocationToUserDataServiceLocationSummaries": {
            "*******": [
              { "services": ["1ELEC"],"id": {"srvLocNbr": "*******","serviceLocation": "*******"}, "location": "**********",
                "address": {"addr1": "*** ******* ****** ** *", "city": "****", "state": "**", "zip": "*****"}, "serviceStatus": "ACTIVE", "lastBillPrevReadDtTm": 1766124000000, "lastBillPresReadDtTm": 1768802400000,
                "activeRateSchedules": ["RES1:TCEC"]
              }]
          },
          "serviceLocationToIndustries": {"*******": ["ELECTRIC"]},
          "providerToDescription": {"TCEC": "Electric Service"},
          "providerToProviderDescription": {"TCEC": "Electric Service"},
          "serviceToServiceDescription": {"1ELEC": "Electric Service"},
          "serviceToProviders": {"1ELEC": ["TCEC"]},
          "serviceLocationToProviders": {"*******": ["TCEC"]}, "consumerClassCode": "", "providerOrServiceDescription": "Electric Service",
          "services": ["1ELEC"]
        },
        {
            'customer': 'YYYYYYYY', 'customerName': 'Customer', 'account': 'XXXXXXX', 'address': 'Address', 'email': '**********', 'inactive': False, 'primaryServiceLocationId': '5XX12XX0YY',
            'serviceLocationIdToServiceLocationSummary': {
              '5XX12XX0YY': {
                'id': {'srvLocNbr': '5XX12XX0YY', 'serviceLocation': '5XX12XX0YY'},
                'location': '7FF1GGHHII',
                'address': {'addr1': 'Street', 'Street': 'City', 'state': 'State', 'zip': 'Zip'},
                'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1767852000000, 'lastBillPresReadDtTm': 1770357600000,
                'meterNumbersToExternalMeterBaseIds': {' ': '5XX12XX0YY+5', '65740': '5XX12XX0YY+2', '20195797': '5XX12XX0YY+3', '557413': '5XX12XX0YY+1', '17700370': '5XX12XX0YY+4'},
                'activeRateSchedules': ['RWM22:1WATR', 'RWM78:1WATR', 'RGM22:2NGAS', 'RES22:3ELEC', 'RSM33:4SEWR']}},
            'serviceLocationToUserDataServiceLocationSummaries': {
              '5XX12XX0YY': [
                { 'services': ['SEWER', 'ELEC', 'TRASH', 'WATER', 'NGAS'],
                 'id': {'srvLocNbr': '5XX12XX0YY', 'serviceLocation': '5XX12XX0YY'},
                 'location': '7FF1GGHHII', 'address': {'addr1': 'Street', 'Street': 'City', 'state': 'State', 'zip': 'Zip'},
                 'serviceStatus': 'ACTIVE', 'lastBillPrevReadDtTm': 1767852000000, 'lastBillPresReadDtTm': 1770357600000,
                 'activeRateSchedules': ['RWM22:1WATR', 'RWM78:1WATR', 'RGM22:2NGAS', 'RES22:3ELEC', 'RSM33:4SEWR']
                }
              ]},
            'serviceLocationToIndustries': {'5XX12XX0YY': ['GAS', 'SEWER', 'TRASH', 'ELECTRIC', 'WATER']},
            'providerToDescription': {'ALL': 'City Utilities'},
            'providerToProviderDescription': {'ALL': 'City Utilities'},
            'serviceToServiceDescription': {'WATER|NGAS|ELEC|SEWER|TRASH': 'City Utilities'},
            'serviceToProviders': {'SEWER': ['4SEWR'], 'ELEC': ['3ELEC'], 'TRASH': ['5TRSH'], 'WATER': ['1WATR'], 'NGAS': ['2NGAS']},
            'serviceLocationToProviders': {'5XX12XX0YY': ['1WATR', '4SEWR', '3ELEC', '2NGAS', '5TRSH']}, 'consumerClassCode': '', 'providerOrServiceDescription': 'City Utilities', 'invoiceGroupNumber': '', 'isUnCollectible': False, 'isAutoPay': True, 'isPendingDisconnect': False, 'isDisconnected': False, 'isMultiService': False, 'agreementStatus': 1, 'disconnectNonPay': False,
            'services': ['WATER', 'NGAS', 'ELEC', 'SEWER', 'TRASH']
        }
    ]

    result = api_instance.parse_locations(test_data)
    expected_locations = [
      SmartHubLocation(
        id="LOCATION_ID",
        service=ELECTRIC_SERVICE,
        description="",
        provider="NOVEC Electric Service",
      ),
      SmartHubLocation(
        id="LOCATION_ID2",
        service=ELECTRIC_SERVICE,
        description="NICKNAME",
        provider="Electric Service",
      ),
      SmartHubLocation(
        id="*******",
        service=ELECTRIC_SERVICE,
        description="",
        provider="Electric Service",
      ),
      SmartHubLocation(
        id="5XX12XX0YY",
        service=ELECTRIC_SERVICE,
        description="",
        provider="3ELEC",
      ),
    ]

    assert len(result) == len(expected_locations)
    for a,b in zip(result, expected_locations):
      compare_SmartHubLocation(a,b)


def test_parse_locations_cvea(api_instance):
    """Test parsing CVEA location with custom service codes and descriptions."""
    test_data = [
      {
        'customer': 'XXXXXX', 'customerName': 'CVEA_USER', 'account': '12345', 'inactive': False,
        'serviceLocationToUserDataServiceLocationSummaries': {
          'LOC_VALDEZ': [
            {'services': ['VELEC'], 'id': {'srvLocNbr': 'LOC_VALDEZ'}, 'description': 'Valdez Home'}
          ],
          'LOC_GLENNALLEN': [
            {'services': ['GELEC'], 'id': {'srvLocNbr': 'LOC_GLENNALLEN'}, 'description': 'Glennallen Shop'}
          ]
        },
        'serviceToServiceDescription': {
            'VELEC': 'Valdez Electric',
            'GELEC': 'Glennallen Electric'
        },
        'serviceToProviders': {'VELEC': ['VE'], 'GELEC': ['GE']},
        'providerToDescription': {'VE': 'CVEA Valdez', 'GE': 'CVEA Glennallen'},
        'services': ['VELEC', 'GELEC']
      }
    ]

    result = api_instance.parse_locations(test_data)
    
    # We expect two locations to be found
    assert len(result) == 2
    
    # Check Valdez location
    valdez = next(l for l in result if l.id == 'LOC_VALDEZ')
    assert valdez.service == ELECTRIC_SERVICE
    assert valdez.description == 'Valdez Home'
    assert valdez.provider == 'CVEA Valdez'

    # Check Glennallen location
    glenn = next(l for l in result if l.id == 'LOC_GLENNALLEN')
    assert glenn.service == ELECTRIC_SERVICE
    assert glenn.description == 'Glennallen Shop'
    assert glenn.provider == 'CVEA Glennallen'


def compare_SmartHubLocation(a: SmartHubLocation, b: SmartHubLocation):
    """comprae two SmartHubLocation objects."""
    # Test that API object is created correctly
    assert a.id == b.id
    assert a.service == b.service
    assert a.description == b.description
    assert a.provider == b.provider
