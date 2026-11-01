"""Builders for small, synthetic source files so the readers are tested offline against real formats."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence

import openpyxl

TAF_AIRPORT_HEADER = ("LOCID", "REGION", "APORT_NAME", "CITY", "STATE", "SITE", "NASPNO", "LATITUDE", "LONGITUDE",
                      "FAC_CLASS", "FAC_LEVEL", "ATCT_FLAG", "PUBLISHED", "SER_VOL", "HUB_SIZE", "HUB_LOCID")
TAF_OPS_HEADER = ("locid", "scenario", "ayear", "itn_Ac", "itn_at", "itn_ga", "itn_mil", "loc_ga", "loc_mil", "tot_overs")
TAF_ENP_HEADER = ("locid", "scenario", "ayear", "aac", "aat", "commuter", "us_flag", "frgn_flag")
ENP_HEADER = ("Rank", "RO", "ST", "Locid", "City", "Airport Name", "S/L", "Hub", "CY 25 Enplanements", "CY 24 Enplanements", "% Change")
ONTIME_HEADER = ("Year", "Quarter", "Month", "DayofMonth", "FlightDate", "Reporting_Airline", "Origin", "Dest", "CRSDepTime",
                 "DepDelay", "DepDel15", "TaxiOut", "Cancelled", "Distance")
T100_HEADER = ("DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "DISTANCE", "UNIQUE_CARRIER", "ORIGIN", "DEST", "DEST_COUNTRY", "YEAR", "MONTH", "CLASS")


def xlsx_bytes(header: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def taf_airports_xlsx() -> bytes:
    rows = [
        ("SFO ", "AWP", "San Francisco International", "SAN FRANCISCO", "CA", "x", 1, "37-37-07.7000N", "122-22-31.5000W", 7, 0, 1, 0, 393000, 3, "SFO"),
        ("BOS", "ANE", "General Edward Lawrence Logan International", "BOSTON", "MA", "x", 2, "42-21-46.6000N", "71-00-23.0000W", 7, 0, 1, 0, 412000, 3, "BOS"),
        ("PWM", "ANE", "Portland International Jetport", "PORTLAND", "ME", "x", 3, "43-38-44.3166N", "70-18-31.0189W", 3, 0, 1, 0, 256000, 1, "NULL"),
        ("XNA", "ASW", "Northwest Arkansas National", "FAYETTEVILLE", "AR", "x", 4, "36-16-54.0000N", "94-18-24.0000W", 3, 0, 1, 0, 0, 1, "NULL"),
        ("00F", "ANM", "BROADUS", "BROADUS", "MT", "x", 5, "45-28-13.7000N", "105-27-25.7000W", 12, 0, 0, 0, 230000, 0, "NULL"),
    ]
    return xlsx_bytes(TAF_AIRPORT_HEADER, rows)


def taf_ops_xlsx() -> bytes:
    rows = [("SFO ", 0, 2023, 376900 - 30000, 20000, 7000, 3000, 0, 0, 100), ("SFO ", 0, 2024, 350000, 21000, 7000, 3304, 0, 0, 0),
            ("SFO ", 1, 2025, 380000, 25000, 7500, 3226, 0, 0, 0), ("SFO ", 1, 2035, 485000, 29000, 9600, 2300, 0, 0, 0),
            ("BOS", 0, 2024, 300000, 50000, 10000, 1000, 500, 0, 0), ("BOS", 1, 2025, 310000, 50000, 10000, 1000, 500, 0, 0),
            ("PWM", 0, 2024, 20000, 10000, 15000, 500, 5000, 0, 0), ("PWM", 1, 2025, 21000, 10000, 15000, 500, 5000, 0, 0),
            ("00F", 0, 2024, 0, 100, 1000, 0, 1200, 0, 0)]
    return xlsx_bytes(TAF_OPS_HEADER, rows)


def taf_enp_xlsx() -> bytes:
    rows = [("SFO ", 0, 2023, 15000000, 100, 2000000, 3000000, 3500000), ("SFO ", 0, 2024, 15383330, 169, 2107019, 3093934, 4181190),
            ("SFO ", 1, 2025, 16456442, 169, 2313177, 3341198, 3995905), ("SFO ", 1, 2035, 20829802, 169, 2981624, 5041813, 5714062),
            ("BOS", 0, 2024, 17000000, 0, 1000000, 1500000, 1500000), ("BOS", 1, 2025, 17500000, 0, 1000000, 1500000, 1600000),
            ("PWM", 0, 2024, 1200000, 0, 80000, 0, 0), ("PWM", 1, 2025, 1250000, 0, 80000, 0, 0)]
    return xlsx_bytes(TAF_ENP_HEADER, rows)


def taf_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Airports.xlsx", taf_airports_xlsx())
        z.writestr("AirportsOperations.xlsx", taf_ops_xlsx())
        z.writestr("Enplanements.xlsx", taf_enp_xlsx())
    return buf.getvalue()


def enplanements_xlsx() -> bytes:
    rows = [(10, "WP", "CA", "SFO", "San Francisco International Airport", "San Francisco International", "P", "L", 26251850, 25078968, 0.0468),
            (16, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 21021153, 21090721, -0.0033),
            (90, "NE", "ME", "PWM", "Portland", "Portland International Jetport", "P", "S", 1287041, 1250000, 0.03),
            (95, "SW", "AR", "XNA", "Fayetteville", "Northwest Arkansas National", "P", "S", 1000000, 950000, 0.05)]
    return xlsx_bytes(ENP_HEADER, rows)


OA_AIRPORTS_CSV = (
    '"id","ident","type","name","latitude_deg","longitude_deg","elevation_ft","continent","iso_country","iso_region","municipality","scheduled_service","icao_code","iata_code","gps_code","local_code","home_link","wikipedia_link","keywords"\n'
    '3747,"KSFO","large_airport","San Francisco International Airport",37.618999,-122.375,13,"NA","US","US-CA","San Francisco","yes","KSFO","SFO","KSFO","SFO",,,\n'
    '3422,"KBOS","large_airport","Logan International Airport",42.3643,-71.0052,20,"NA","US","US-MA","Boston","yes","KBOS","BOS","KBOS","BOS",,,\n'
    '3741,"KPWM","medium_airport","Portland International Jetport",43.646198,-70.309303,76,"NA","US","US-ME","Portland","yes","KPWM","PWM","KPWM","PWM",,,\n'
    '3900,"KXNA","medium_airport","Northwest Arkansas National Airport",36.281898,-94.306801,1287,"NA","US","US-AR","Fayetteville","yes","KXNA","XNA","KXNA","XNA",,,\n'
    '6523,"00A","heliport","Total RF Heliport",40.070985,-74.933689,11,"NA","US","US-PA","Bensalem","no",,,"K00A","00A",,,\n'
)
OA_RUNWAYS_CSV = (
    '"id","airport_ref","airport_ident","length_ft","width_ft","surface","lighted","closed","le_ident","le_latitude_deg","le_longitude_deg","le_elevation_ft","le_heading_degT","le_displaced_threshold_ft","he_ident","he_latitude_deg","he_longitude_deg","he_elevation_ft","he_heading_degT","he_displaced_threshold_ft"\n'
    '1,3747,"KSFO",11870,200,"ASPH",1,0,"10L",,,,,,"28R",,,,,\n'
    '2,3747,"KSFO",11381,200,"ASPH",1,0,"10R",,,,,,"28L",,,,,\n'
    '3,3747,"KSFO",8650,200,"ASPH",1,0,"01L",,,,,,"19R",,,,,\n'
    '4,3747,"KSFO",7650,200,"ASPH",1,0,"01R",,,,,,"19L",,,,,\n'
    '5,3747,"KSFO",9000,200,"ASPH",1,1,"99",,,,,,"99",,,,,\n'
    '6,3422,"KBOS",10083,150,"ASPH",1,0,"04R",,,,,,"22L",,,,,\n'
    '7,3422,"KBOS",5000,100,"ASPH",1,0,"14",,,,,,"32",,,,,\n'
    '8,3422,"KBOS",2557,100,"ASPH",1,0,"15L",,,,,,"33R",,,,,\n'
    '9,3741,"KPWM",7200,150,"ASPH",1,0,"11",,,,,,"29",,,,,\n'
    '10,3741,"KPWM",6100,150,"ASPH",1,0,"18",,,,,,"36",,,,,\n'
    '11,3900,"KXNA",8800,150,"CONC",1,0,"16",,,,,,"34",,,,,\n'
)


def ontime_zip(month: int = 1, year: int = 2025) -> bytes:
    rows = [",".join(ONTIME_HEADER)]
    # SFO: 6 departures, 1 cancelled, 2 delayed, taxi-out 10..30, one 3,000+ mile leg (to HNL-like distance)
    specs = [("SFO", "LAX", 5.0, 0, 12.0, 0, 337), ("SFO", "JFK", 20.0, 1, 18.0, 0, 2586), ("SFO", "HNL", -3.0, 0, 15.0, 0, 2398),
             ("SFO", "ANC", 40.0, 1, 30.0, 0, 2018), ("SFO", "BOS", "", "", "", 1, 2704), ("SFO", "EWR", 2.0, 0, 10.0, 0, 2565),
             ("SFO", "GUM", 1.0, 0, 11.0, 0, 5800), ("BOS", "SFO", 0.0, 0, 20.0, 0, 2704), ("PWM", "BOS", 3.0, 0, 8.0, 0, 95)]
    for i, (o, d, delay, d15, taxi, canc, dist) in enumerate(specs, 1):
        rows.append(",".join(str(x) for x in (year, 1, month, i, f"{year}-{month:02d}-{i:02d}", "UA", o, d, "0800", delay, d15, taxi, canc, dist)))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_{year}_{month}.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


def t100_csv(year: int = 2025) -> str:
    rows = [",".join(T100_HEADER)]
    specs = [(100, 15000, 12000, 337, "UA", "SFO", "LAX", "US", "F"), (50, 15000, 13500, 5130, "UA", "SFO", "NRT", "JP", "F"),
             (30, 0, 0, 5130, "FX", "SFO", "NRT", "JP", "G"), (20, 3000, 2400, 2586, "UA", "SFO", "JFK", "US", "F"),
             (200, 30000, 24000, 2704, "DL", "BOS", "SFO", "US", "F"), (10, 1500, 1400, 3255, "DL", "BOS", "LHR", "GB", "F"),
             (300, 15000, 10000, 95, "9E", "PWM", "BOS", "US", "F")]
    for s in specs:
        rows.append(",".join(str(x) for x in (s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], year, 6, s[8])))
    return "\n".join(rows) + "\n"


NAS_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Sun Nov 1 09:05:29 2026 GMT</Update_Time>
<Delay_type><Name>Airport Closures</Name><Airport_Closure_List><Airport><ARPT>LAX</ARPT><Reason>!LAX 05/277 LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT</Reason><Start>May 27 at 18:26 UTC.</Start><Reopen>May 28 at 16:00 UTC.</Reopen></Airport></Airport_Closure_List></Delay_type>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>SFO</ARPT><Reason>WEATHER / LOW CEILINGS</Reason><End_Time>1700Z</End_Time></Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay><ARPT>SFO</ARPT><Reason>WX</Reason><Arrival_Departure Type="Departure"><Min>31 minutes</Min><Max>45 minutes</Max><Trend>Increasing</Trend></Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""

PROFILE_TEXT = (
    "VISUAL – 28/01 SIDE-BYES Airport Capacity Profile SFO 4 The capacity rate range in Visual conditions for 28/01 Side-Byes is "
    "currently 104- 107 operations per hour. Runway 28L is used as a departure runway. The capacity rate range in Visual conditions "
    "for 28RT Stagger-Byes is currently 83-85 operations per hour. The capacity rate range in Marginal conditions for 28/01 Side-Byes "
    "is currently 93-98 operations per hour. The capacity rate range in Instrument conditions for 28/01 Intrailis currently 76-78 "
    "operations per hour. The capacity rate range in Low Instrument conditions in East flow is currently 60 - 62 operations per hour."
)
