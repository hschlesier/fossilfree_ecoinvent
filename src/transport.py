import bw2io as bi
import bw2data as bd
import numpy as np
import warnings
np.warnings = warnings
import carculator as cc
import carculator_truck as cct
import bw2data as bd
import math
from datetime import datetime
from pathlib import Path
import uuid
import random
import pandas as pd

import checks_and_balances as cb
import importlib
importlib.reload(cb)
from checks_and_balances import track_changes
import utils as util
importlib.reload(util)
from utils import migrate_exchanges, flatten, get_modified_fossil_reduction_factor, change_geographies, defossilize_biosphere_flows, add_biosphere_flows, output_to_self, comment_to_dict, add_technosphere_flows_to_activity, get_fuel_replacement_split, check_bio_or_synfuel, import_emission_factors, replace_fuel, import_synfuel_dict, import_fossil_identifiers, import_not_electrifiable_fuels

def import_vehicles():
    parent_dir = Path.cwd().parent
    with open(parent_dir / 'data/raw/vehicles.txt') as file:
        vehicles = [line.rstrip() for line in file]
    return vehicles

def create_passenger_vehicles(car_year, database, ei_version, transport_location):
    """
    Creating electric passenger cars with the carculator from https://github.com/romainsacchi
    and merge it to the input database.
    
    Args:
                car_year:    Year of scenario
                database:    Database to be manipulated
                ei_version:  version of ecoinvent database e.g. "ecoinvent 3.8 cutoff"
                db_path:     Filepath for folder with LCI databases
                
    Returns:    None
                 
    """
    parent_dir = Path.cwd().parent

    for act in [act for act in database if ('transport, passenger car, fuel cell electric' in act['name']
                                           or "transport, passenger car, battery electric" in act['name'])]:
        if any(size in act['name'] for size in ['Small', 'Medium', 'Large']):
            print('----')
            print('Electric passenger cars already in database')
            print('----')
            return
            
    if 'carculator db' not in list(bd.databases):    
        cip = cc.CarInputParameters()
        cip.static()  # iteratively use cip.stochastic() to create models based on a probability model

        scope = {'powertrain': ['BEV', 'FCEV'],
                 'size': ['Small', 'Medium', 'Large'],
                 'year': car_year}
        dcts, array = cc.fill_xarray_from_input_parameters(cip, scope=scope)  # scope could be adjusted if needed/wanted
        if len(car_year)>1:
            array = array.interp(year=car_year, kwargs={'fill_value': 'extrapolate'})
        cm = cc.CarModel(array, cycle='WLTC')
        cm.set_all()
        
        ic = cc.InventoryCalculation(cm.array)

        #export
        imp=ic.export_lci_to_excel(software_compatibility="brightway2",
                               directory=parent_dir/ 'data' /'artifacts',
                               ecoinvent_version=ei_version)

        #import carculator db
        date=str(datetime.now())[:10]
        path = parent_dir/ 'data' /'artifacts' /'carculator_inventory_export_{}_brightway2.xlsx'.format(date)

        imp = bi.ExcelImporter(path)
        imp.apply_strategies()
        if ei_version!='3.8':
            new_data = migrate_exchanges(imp.data.copy(), from_version='3.8', to_version='3.9')
            imp.data = new_data
        imp.match_database(database.name, fields=('name','unit','location',"reference product"))
        imp.match_database("biosphere3", fields=('name','unit',"categories"))
        imp.match_database(fields=('name', 'unit', 'location'))
        #imp.add_unlinked_biosphere_flows_to_current_database()
        imp.statistics()
        new_imp_data = change_geographies(imp_data = imp.data.copy(), 
                                  from_location='RER', 
                                  to_location=transport_location, 
                                  database_only=True, 
                                  cc_name='carculator db', 
                                  database=database)
        imp.data = new_imp_data
        imp.write_excel(only_unlinked=True)
        imp.write_database()

    # merge the created cars to the ecoinvent database
    delete_duplicates_in_carculator_db(database, "carculator db")
    
    bd.utils.merge_databases(database.name, 'carculator db')
    
    bd.databases[database.name]["modified"]=str(datetime.now()).replace(" ","T")
    bd.databases[database.name]=bd.databases[database.name]

def create_lorries(database, truck_year, ei_version, transport_location):
    """
    Creating electric lorries/trucks with the carculator_trucks from https://github.com/romainsacchi
    and add it to the input database
    
    Arguments:
                car_year:    Year of scenario
                database:    Database to be manipulated
                ei_version:  version of ecoinvent database e.g. "ecoinvent 3.8 cutoff"
                db_path:     Filepath for folder with LCI databases
                
    Returns:    None
    """
    parent_dir = Path.cwd().parent

    for act in [act for act in database if 'transport, freight, lorry' in act['name']
                                           and any(kind in act["name"] for kind in ['battery', 'fuel cell'])]:
        print('----')
        print('Electric lorries already in database')
        print('----')
        return
    
    if 'carculator db' not in list(bd.databases):
        tip = cct.TruckInputParameters()
        
        tip.static()  # tdcts, tarray = fill_xarray_from_input_parameters(tip)

        scope = {
            "powertrain": ["BEV", "FCEV"],
            "year": truck_year,
            "size": ['3.5t', '7.5t', '18t', '26t', '32t', '40t', '60t'] }
        dcts, array = cct.fill_xarray_from_input_parameters(tip, scope=scope)
        if len(truck_year)>1:
            array = array.interp(year=truck_year, kwargs={'fill_value': 'extrapolate'})
        tm = cct.TruckModel(array, cycle='Long haul')
        tm.set_all()

        ic = cct.InventoryCalculation(tm, scope=scope)

        #export truck carculator db
        i=ic.export_lci_to_excel(software_compatibility="brightway2",
                               directory=parent_dir/ 'data' /'artifacts',
                               ecoinvent_version=ei_version)

        #import carculator db
        date=str(datetime.now())[:10]
        path = parent_dir/ 'data' / 'artifacts'/ 'carculator_inventory_export_{}_brightway2.xlsx'.format(date)
        i = bi.ExcelImporter(path) 
        i.apply_strategies()
        if ei_version!='3.8':
            new_data = migrate_exchanges(i.data.copy(), from_version='3.8', to_version='3.9')
            i.data = new_data
        i.match_database(fields=["name", "unit", "location"])
        i.match_database(database.name, fields=["reference product", "name", "unit", "location"])
        i.match_database('biosphere3', fields=["name", "unit", "categories"])
        #i.add_unlinked_biosphere_flows_to_current_database()
        i.statistics()
        new_imp_data = change_geographies(imp_data = i.data.copy(), 
                                  from_location='RER', 
                                  to_location=transport_location, 
                                  database_only=True, 
                                  cc_name='carculator db', 
                                  database=database)
        i.data = new_imp_data
        i.write_excel(only_unlinked=True)
        i.write_database()
        
    delete_duplicates_in_carculator_db(database, "carculator db")

    bd.utils.merge_databases(parent_db=database.name, other='carculator db')
    
    bd.databases[database.name]["modified"]=str(datetime.now()).replace(" ","T")
    bd.databases[database.name]=bd.databases[database.name]

def delete_duplicates_in_carculator_db(ref_database, database_to_clean_name):
    """
    Deletes duplicates in one database before merging with another.
    Args:
               ref_database: database as reference
               database_to_clean_name: duplicates are deleted in this databases
    Returns:
                None
    
    """
    database_to_clean=bd.Database(database_to_clean_name)
    ref_act_codes=[act["code"] for act in ref_database]
    count=0
    for act in database_to_clean:
        if act["code"] in ref_act_codes:
            act.delete()
            count+=1
    if count>0:
        print("Deleted {0} duplicate activities in {1}".format(count, database_to_clean_name))

def add_new_diesel_market(eidb, altered_activities, synfuel_split_dict):
    """
    Creating new global diesel markets for biodiesel and synthetic diesel.
    
    Args:
        eidb:               Database to manipulate
        altered_activities: Dictionary of altered activities for documentation
        synfuel_split_dict: Split of synthetic and bio fuels
    Returns:
        altered_activities: Updated dictionary of altered activities for documentation
    
    """
    #create synfuel and biofuel markets for diesel
    diesel_market_code    = uuid.uuid4().hex
    diesel_market_name    = "market for diesel, biodiesel and synthetic diesel blend"
    diesel_market_product = "diesel, biodiesel and synthetic diesel blend"
    
    if diesel_market_name not in [act["name"] for act in eidb]:
        diesel_market = eidb.new_activity(code=diesel_market_code,
                                          name=diesel_market_name,
                                          unit='kilogramm',
                                          type='process',
                                          location="GLO")
        diesel_market.save()
        diesel_market["reference product"]= diesel_market_product
        diesel_market["production amount"]= 1.0
        diesel_market.save()

        syndiesels=[act for act in eidb 
             if "diesel production, synthetic, from electrolysis-based hydrogen, energy allocation, at fuelling station"==act["name"]]
        biodiesels=[act for act in eidb if "Biodiesel" in act["name"] and "station" in act["name"]]


        #add synthetic diesel
        add_technosphere_flows_to_activity(diesel_market,syndiesels, len(syndiesels)*[synfuel_split_dict["syngen"]/len(syndiesels)])
        
        #add biodiesel
        add_technosphere_flows_to_activity(diesel_market,biodiesels, len(biodiesels)*[synfuel_split_dict["biogen"]/len(biodiesels)])

        altered_activities = track_changes(diesel_market, altered_activities, 'activity creation')
    return altered_activities

def electric_lorry_market_setup(database, lorry_type_split, altered_activities):
    """
    Create a market for electric lorries based on the input type split of Battery- and fuel-cell EV.
    
    
    Arguments: 
                database:           Database to be manipulated
                lorry_type_split:   Share of drives: BEV, FCEV, ICE
                altered_activities: List of altered activities
    Return:
        updated list of altered activities
    """
    print("Creating electric lorry markets.")
    EV_total = lorry_type_split['FCEV']+lorry_type_split['BEV']
    if lorry_type_split['ICE'] <= 1:
        if [act for act in database if 'market for electric lorry' in act['name']]==[]:
            size =['3.5-7.5', '7.5-18', '18-32', '>32']
            duty_trucks=[act for act in database if 'duty truck' in act['reference product']]
            for lorry_size in size:

                lorry_market_name = "market for electric lorry, " + lorry_size + ' tons'
                lorry_market_code = uuid.uuid4().hex

                # Create activities
                lorry_market = database.new_activity(code=lorry_market_code,
                                                   name=lorry_market_name,
                                                   unit='unit',
                                                   type='process',
                                                   location='GLO')
                lorry_market.save()
                lorry_market['reference product']= 'lorry, electric'
                lorry_market['production amount']=  1.0
                lorry_market.save()
                altered_activities = track_changes(lorry_market, altered_activities, 'activity creation')

                # normalizing electric options:
                bev_typesplit = lorry_type_split['BEV'] / EV_total
                fcev_typesplit = lorry_type_split['FCEV'] / EV_total

                BEVs  = [act for act in duty_trucks if 'battery' in act['name']
                                             and is_in_size(act['name'], lorry_size)]
                FCEVs = [act for act in duty_trucks if 'fuel cell' in act['name']
                                             and is_in_size(act['name'], lorry_size)]
                
                BEV_amounts  = [lorry_type_split['BEV']/len(BEVs)]*len(BEVs)
                FCEV_amounts = [lorry_type_split['FCEV']/len(FCEVs)]*len(FCEVs)

                add_technosphere_flows_to_activity(lorry_market, BEVs+FCEVs, BEV_amounts+FCEV_amounts)
    
    print("Creating markets for transport, freight, electric lorry.")
    #creating market for transport, electric lorry 
    if lorry_type_split['ICE'] <= 1:
        if [act for act in database if 'market for transport, freight, electric lorry' in act['name']]==[]:
            electric_lorry_transports=[act for act in database 
                                           if 'transport, freight, lorry' in act['name'] and 'electric' in act['name']]
            lorry_sizes = ['3.5-7.5', '7.5-18', '18-32', '>32']
            sorted_electric_lorry_transports=[[act for act in electric_lorry_transports 
                                                   if is_in_size(act['name'], size)] for size in lorry_sizes]
            for size in lorry_sizes:
                
                transport_list = sorted_electric_lorry_transports[lorry_sizes.index(size)]
                
                lorry_transport_market_name = "market for transport, freight, electric lorry, " + size + ' tons'
                lorry_transport_market_code = uuid.uuid4().hex
                product_name                = 'transport, freight, electric lorry'
                transport_market = database.new_activity(code=lorry_transport_market_code,
                                                   name=lorry_transport_market_name,
                                                   unit='ton kilometer',
                                                   type='process',
                                                   location='GLO')
                transport_market.save()
                transport_market['reference product']= product_name
                transport_market['production amount']=  1.0
                transport_market.save()
                
                BEV_transport  = [act for act in electric_lorry_transports if 'battery' in act['name']
                                                              and is_in_size(act['name'], size)]
                FCEV_transport = [act for act in electric_lorry_transports if 'fuel cell' in act['name']
                                                              and is_in_size(act['name'], size)]
                
                BEV_amounts  = [lorry_type_split['BEV']/len(BEV_transport)]*len(BEV_transport)
                FCEV_amounts = [lorry_type_split['FCEV']/len(FCEV_transport)]*len(FCEV_transport)
                
                add_technosphere_flows_to_activity(transport_market, BEV_transport+FCEV_transport, BEV_amounts+FCEV_amounts)
                altered_activities = track_changes(transport_market, altered_activities, 'activity creation')
    
    print("Creating electric lorry production with refrigeration.")
    #creating electric lorry production with refrigeration
    sizes       = ['3.5-7.5', '7.5-18', '18-32', '>32']
    refrigerants= ['R134a', 'carbon dioxide, liquid']
    temp_modes  = ['cooling', 'freezing']
    drives      = ['fuel cell', 'battery']
    abrev       = ['FCEV', 'BEV']
        
    if lorry_type_split['ICE'] <= 1:
        if [act for act in database if 'electric lorry production' in act['name']]==[]:
            factory= [act for act in database if 'market for road vehicle factory'==act['name']][0]
            for refrigerant in refrigerants:
                refrig_machine = [act for act in database if 'market for refrigeration machine, '+refrigerant in act['name']][0]
                for size in sizes:
                    for drive in drives:
                        trucks = [act for act in database 
                                       if 'duty truck' in act['name']
                                       and drive in act['name']
                                       and is_in_size(act['name'], size)]

                        process_name = 'electric lorry production, '+drive+', with refrigeration machine, '+refrigerant+', '+size+'t'
                        process_code = uuid.uuid4().hex
                        
                        lorry = database.new_activity(code=process_code,
                                                   name=process_name,
                                                   unit='unit',
                                                   type='process',
                                                   location='GLO',
                                                   comment='Multiple truck inputs reflects average truck size in size range')
                        lorry.save()
                        lorry['reference product']= 'Duty truck, '+drive+' electric, with refrigeration machine'
                        lorry['production amount']= 1.0
                        lorry.save()

                        inputs=flatten([trucks, [factory], [refrig_machine]])
                        amounts=[1/len(trucks)]*len(trucks)+[8.73e-07, 1] #nr of trucks, road vehicle factor, refrigeration machine
                        add_technosphere_flows_to_activity(lorry, inputs, amounts)

                        altered_activities = track_changes(lorry, altered_activities, 'activity creation')
    
    print("Creating transport, freight, electric lorry with refrigeration machine.")                    
    #create transport, freight, electric lorry with refrigeration machine
    if lorry_type_split['ICE'] <= 1:
        if [act for act in database if 'transport, freight, lorry' in act['name'] 
                                and 'electric, with refrigeration machine' in act['name']]==[]: 
        
            electric_transports=[act for act in database if act["reference product"]=="transport, freight, lorry"]

            for electric_transport in electric_transports:
                for temp_mode in temp_modes:
                    for refrigerant in refrigerants:
                        for drive in drives:
                            if drive in electric_transport['name']:
                                refrig_transport = electric_transport.copy()

                                refrig_transport["name"]='transport, freight, lorry, '+drive+ ' electric, with refrigeration machine, '
                                refrig_transport["name"]+=refrigerant+', '+temp_mode
                                refrig_transport["reference product"]+=", "+temp_mode
                                
                                ref_truck_exchange=[exc for exc in refrig_transport.technosphere() 
                                                                if "duty truck" in exc.input["reference product"]
                                                                and "refrigeration machine" not in exc.input["reference product"]][0]
                                
                                size   = ref_truck_exchange.input['name'][ref_truck_exchange.input['name'].index('gross weight')-5:ref_truck_exchange.input['name'].index('gross weight')-2].strip()
                                
                                refrig_transport["code"]=uuid.uuid4().hex
                                refrig_transport["name"]+=', '+size+'t'
                                refrig_transport.save()
                                
                                ref_amount = ref_truck_exchange.amount

                                ref_truck_exchange.delete() #delete truck without refrigeration machine

                                trucks=[act for act in database if 'Duty truck' in act['reference product']
                                                                  and 'refrigeration machine' in act['reference product']
                                                                  and compatible_size(act['name'], size)
                                                                  and refrigerant in act['name']
                                                                  and drive in act['name']]

                                add_technosphere_flows_to_activity(refrig_transport, trucks, len(trucks)*[ref_amount/len(trucks)])

                                #Taken from ecoinvent 3.8 cutoff
                                energy_demand           = 0.92593 * 0.051331 * (1/3.6) #kg*day/ton kilometer * MJ/kg*day *kWh/MJ [kWh]
                                refrigerant_demand      = 7.69e-08 #carbon dioxide, liquid / refrigerant R134a

                                cooling_operation= [act for act in database 
                                       if act['name']=='operation, reefer, cooling, 40-foot, high-cube, '+refrigerant+' as refrigerant'][0]
                                add_biosphere_flows(refrig_transport, cooling_operation) #adding emission

                                #adding carbon dioxide, liquid / refrigerant R134a
                                refrig_markets = [act for act in database if act['name']=='market for '+refrigerant] 
                                add_technosphere_flows_to_activity(refrig_transport, 
                                                                           refrig_markets, len(refrig_markets)*[refrigerant_demand])

                                #add energy (electricity or hydrogen) for cooling / freezing
                                if drive=='battery':
                                    fuels = [act for act in database 
                                        if act['reference product']=='electricity, low voltage, for battery electric vehicles']
                                    add_technosphere_flows_to_activity(refrig_transport, fuels, len(fuels)*[energy_demand])

                                elif drive=='fuel cell':
                                    fuel = [act for act in database 
                                        if act['reference product']=='fuel'][0]
                                    property = comment_to_dict(electric_transport['comment'])
                                    tank_to_wheel = property['Tank-to-wheel energy consumption [kj/km]']
                                    fuel_per_ton_km= sum([exc.amount for exc in electric_transport.technosphere() 
                                                              if exc.input['reference product']=='fuel'])
                                    #(kg/tonkm)/((KJ/tonkm)*(MJ/KJ)*(kWh/MJ))      [kgH2/kWh]
                                    kgH2_per_kWh = fuel_per_ton_km/(tank_to_wheel*1000/3.6)
                                    kgH2_amount  = energy_demand*kgH2_per_kWh #[kgH2]
                                    add_technosphere_flows_to_activity(refrig_transport, [fuel], [kgH2_amount])

                                output_to_self(refrig_transport) # alter output to self

                                altered_activities = track_changes(refrig_transport, altered_activities, 'activity creation')

    print("Creating market for transport, freight, electric lorry with refrigeration machine.") 
    #create market for transport, freight, electric lorry with refrigeration machine
    if lorry_type_split['ICE'] <= 1:

        market_code_dict ={}
        market_code_dict['market']={}
        market_code_dict['transport']={}
        
        lorry_sizes =['3.5-7.5', '7.5-16', '16-32', '>32'] #sizes in ecoinvent 3.8
        if [act for act in database if 'market for transport, freight, electric lorry with refrigeration' in act['name']]==[]:        
            #get share of refrigerants
            all_lorry_sizes =['3.5', '7.5', '18', '26', '32', '40', '60'] #sizes in carculator
            old_market  =[act for act in database 
                                      if act['name']=='market for transport, freight, lorry with refrigeration machine, cooling'][0]
            R134a_share =sum([exc.amount for exc in old_market.technosphere() if 'R134a' in exc.input['name']])
            refrigerant_shares = [R134a_share, 1-R134a_share] #share CO2, liquid, share R134a
            for temp_mode in temp_modes:
                ref_lorry_transport_market_name = 'market for transport, freight, electric lorry with refrigeration machine, '+temp_mode
                product_name                    = 'transport, freight, electric lorry with refrigeration machine, '+temp_mode
                ref_lorry_transport_market_code = uuid.uuid4().hex
                market_code_dict['market'][temp_mode]            = ref_lorry_transport_market_code
                #create market
                market= database.new_activity(code=ref_lorry_transport_market_code,
                                                   name=ref_lorry_transport_market_name,
                                                   unit='ton kilometer',
                                                   type='process',
                                                   location='GLO')
                market.save()
                market['reference product']= product_name
                market['production amount']= 1.0
                market.save()           
                
                #get share of sizes (tons) for market
                if temp_mode=='freezing':
                    transport_freezing = [act for act in database 
                                               if act['name']=='transport, freight, lorry with reefer, freezing'
                                                  and act['location']=='GLO'][0]
                    size_share =[sum([exc.amount for exc in transport_freezing.technosphere()
                                               if size in exc.input['name']]) for size in lorry_sizes]
                elif temp_mode=='cooling':
                    exchanges =[exc for exc in flatten([list(exc.input.technosphere()) for exc in old_market.technosphere()])]
                    size_share = get_lorry_size_share(exchanges, all_lorry_sizes, 'relative', True)

                    #add technosphere flows
                    input_list, amounts = [], []
                    for refrigerant in refrigerants:
                        refr_share= refrigerant_shares[refrigerants.index(refrigerant)]
                        for drive in drives:
                            drive_factor = lorry_type_split[abrev[drives.index(drive)]]/EV_total
                            for size in all_lorry_sizes:
                                act_name = "transport, freight, lorry, "+drive+ ' electric, with refrigeration machine, '
                                inputs=[act for act in database if act_name in act['name']
                                                              and refrigerant in act['name']
                                                              and temp_mode in act['name']
                                                              and size in act['name']]
                                amount=len(inputs)*[refr_share*size_share[all_lorry_sizes.index(size)]*drive_factor]
                                input_list+=inputs
                                amounts+=amount
                    amounts = [amount/sum(amounts) for amount in amounts] #balance to 1
                    add_technosphere_flows_to_activity(market, input_list, amounts)

                    altered_activities = track_changes(market, altered_activities, 'activity creation')
                             
            #create transport, freight, electric lorry with reefer, cooling / freezing
            for temp_mode in temp_modes:
                old_reefer_transports= [act for act in database if act['name']=='transport, freight, lorry with reefer, '+temp_mode]
                if old_reefer_transports==[]:
                    raise Exception("Can't find activities: ", 'transport, freight, lorry with reefer, '+temp_mode)
                for transport in old_reefer_transports:
                    exchanges = [exc for exc in transport.technosphere() if exc.input['unit']=='ton kilometer']
                    size_share = get_lorry_size_share(exchanges, lorry_sizes, 'absolute', False)

                    transport_name = 'transport, freight, electric lorry with reefer, '+temp_mode
                    product_name   = 'transport, freight, electric lorry with reefer, '+temp_mode
                    transport_code = uuid.uuid4().hex
                    market_code_dict['transport'][temp_mode]= transport_code
                    try:
                        act=database.get(transport_code)
                        raise Exception("This code is taken: ", act)
                    except:
                        new_transport= database.new_activity(code=transport_code,
                                                   name=transport_name,
                                                   unit=transport['unit'],
                                                   type='process',
                                                   location=transport['location'])
                        new_transport.save()
                        new_transport['reference product']= product_name
                        new_transport['production amount']= 1.0
                        new_transport.save()

                    inputs = [[act for act in database if 'transport, freight, lorry' in act['name'] # electric lorries
                                                                  and 'electric' in act['name']
                                                                  and is_in_size(act['name'], size)] for size in lorry_sizes]
                    amounts=[] #premlinary empty array
                    inputs_not_null = []
                    for input_array in inputs:
                        current_size_share = size_share[inputs.index(input_array)]
                        if current_size_share>0:
                            for inpt in input_array:
                                if 'battery' in inpt['name']:
                                    drive_factor=lorry_type_split['BEV']/EV_total
                                elif 'fuel cell' in inpt['name']:
                                    drive_factor=lorry_type_split['FCEV']/EV_total
                                amount = current_size_share*drive_factor/len(input_array)
                                amounts.append(amount)
                                inputs_not_null.append(inpt) 
                    amounts=[amount/sum(amounts) for amount in amounts]
                    if abs(sum(amounts)-sum(size_share))>0.001:
                         raise Exception(new_transport, "Inputs: amounts do not sum up to ", sum(size_share)," | ", sum(amounts))
                    
                    temp_operation_amount = [0.925925925925926] #kg*day operation, reefer, cooling/freezing
                    temp_operation        = [act for act in database if act['name']=='market for operation, reefer, '+temp_mode]
                    
                    add_technosphere_flows_to_activity(new_transport, inputs_not_null+temp_operation, amounts+temp_operation_amount)
                    altered_activities = track_changes(new_transport, altered_activities, 'activity creation')

                    #create market of transport, freight, electric lorry with reefer, cooling / freezing
                    market_name = 'market for '+transport_name
                    market_code = 'market'+transport_code

                    market= database.new_activity(code=market_code,
                                               name=market_name,
                                               unit=transport['unit'],
                                               type='process',
                                               location=transport['location'])
                    market.save()
                    market['reference product']= product_name
                    market['production amount']= 1.0
                    market.save()

                    add_technosphere_flows_to_activity(market, [new_transport], [1])

        else:
            for temp_mode in temp_modes:
                transport_code = [act['code'] for act in database if act['name']=='transport, freight, electric lorry with reefer, '+temp_mode][0]
                market_code    = [act['code'] for act in database if act['name']=='market for transport, freight, electric lorry with refrigeration machine, '+temp_mode][0]
                market_code_dict['transport'][temp_mode] = transport_code
                market_code_dict['market'][temp_mode] = market_code

            
    print("Created electric lorry markets.")        
    return altered_activities, market_code_dict
                             
def get_lorry_size_share(exchanges, lorry_sizes, mode, is_18_to_16):
    """
    Returns share of lorry sizes in exchanges.
    
    """
    total = sum([exc.amount for exc in exchanges])
    if is_18_to_16:
        try:
            lorry_sizes[lorry_sizes.index('18')]='16'
        except:
            raise ValueError("No 18t in lorry_sizes", lorry_sizes)
    if mode=='relative':
        size_share = [sum([exc.amount for exc in exchanges if size in exc.input['name']])/total for size in lorry_sizes]
        size_share =[share/sum(size_share) for share in size_share]
    elif mode=='absolute':
        size_share = [sum([exc.amount for exc in exchanges if size in exc.input['name']]) for size in lorry_sizes]
    else:
        raise Exception(mode, "has to be absolute or relative.")
    return size_share
                             
def is_in_size(name, size):
    """
    Checks if a lorry is within a certain size.
    """
    min_max = [float(ele) for ele in size.replace('>','').split('-') if ele!='']
    if len(min_max)==1: #if >32
        min_max.append(1000) #add large max value
    try:
        ton=float(name[name.index('gross weight')-5:name.index('gross weight')-2].strip())
    except:
        ton=name[len(name)-8:len(name)-1].replace(',','').strip()
        return ton==size  
    try:
        bools = ton >= min_max[0] and ton <= min_max[1]
    except:
        raise Exception(min_max, "cannot be compared to ", ton)
    return bools

def compatible_size(name, size):
    """
    Checks if a lorry is within a certain size. 
    """
    ton=name[len(name)-8:len(name)-1].replace(',','').strip()
    if '>32' in name:
        return float(size) >= 32
    min_max = [float(ele) for ele in ton.replace('>','').split('-') if ele!='']
    try:
        bools = float(size) >= min_max[0] and float(size) <= min_max[1]
    except:
        raise Exception(min_max, "cannot be compared to ", ton)
    return bools
                         
def scale_lorry_markets(database, lorry_type_split, code_dict, altered_activities):
    """
    Scaling the existing fossil truck in the lorry markets and replace the reduced amount with electric vehicle market
    
    Arguments: 
                database:           Database to be manipulated
                lorry_type_split:   power train split for lorries
                altered_activities: List of altered activities
    Return:
        updated list of altered activities
    """
    print("Scaling lorry markets.")
    if lorry_type_split['ICE'] <= 1:
        market_sizes         = ['3.5-7.5', '7.5-16', '16-32', '>32']
        electric_lorry_sizes = ['3.5-7.5', '7.5-18', '18-32', '>32']
        markets= [act for act in database
                       if 'market for transport, freight, lorry' in act['name']
                          and 'all sizes' not in act['name']  # market of markets
                          and 'vegetable' not in act['name']
                          and 'unspecified' not in act['name']  # market of markets
                          and 'refrigeration' not in act['name']
                          and 'fatty acid methyl ester 100%' not in act['name']
                          and 'with reefer' not in act['name']]
            
        sorted_markets=[[act for act in markets if size in act['name']] for size in market_sizes]
        for sorted_market_list in sorted_markets:
            consumptions = flatten([list(market.upstream()) for market in sorted_market_list])
            electric_lorry_size = electric_lorry_sizes[sorted_markets.index(sorted_market_list)]
            electric_lorry_transport_markets = [act for act in database
                                           if 'market for transport, freight, electric lorry, '+electric_lorry_size in act['name']]
            
            #scale inputs of all consumers to market for transport, freight, lorry
            for consumption in consumptions:
                ex_amount = consumption.amount
                consumer  = consumption.output
                
                consumption['amount']*=lorry_type_split['ICE'] #scale down ICE lorry
                consumption.save()
                
                #add market for transport, electric lorry, [size]
                amounts = [ex_amount*(1-lorry_type_split['ICE'])/len(electric_lorry_transport_markets)
                                           for act in electric_lorry_transport_markets]
                add_technosphere_flows_to_activity(consumer, electric_lorry_transport_markets, amounts)
                altered_activities = track_changes(consumer, altered_activities, 'scaling')
         
        #lorry with refrigeration machine or with reefer
        for market in [act for act in database if ('market for transport, freight, lorry with refrigeration machine' in act['name']
                                                   and not 'EURO' in act['name'])
                                                   or 'market for transport, freight, lorry with reefer' in act['name']]:
            for consumption in market.upstream():
                ex_amount = consumption.amount
                consumer  = consumption.output
                            
                consumption['amount']*=lorry_type_split['ICE'] #scale down ICE lorry with refrigeration
                consumption.save()
                             
                #add electric lorry with refrigeration to consumer
                temp_mode = market['name'].split(',')[3].strip() #'cooling'/'freezing'
                if temp_mode!='freezing' and temp_mode!='cooling':
                    raise Exception("Check name of market for transport, freight, lorry with refrigeration machine.", temp_mode)
                if 'refrigeration machine' in market['name']:
                    input = [database.get(code_dict['transport'][temp_mode])]
                else:
                    input = [database.get(code_dict['market'][temp_mode])]
                add_technosphere_flows_to_activity(consumer, input, [ex_amount*(1-lorry_type_split['ICE'])])
                 
                altered_activities = track_changes(market, altered_activities, 'scaling')
    print("Scaled lorry markets.")
    return altered_activities

def get_train_traction_data():
    parent_dir = Path.cwd().parent
    #https://treeze.ch/fileadmin/user_upload/downloads/Publications/Case_Studies/Mobility/544-LCI-Rail-Transport-Services-v2.0.pdf p. 17
    traction_data = pd.read_excel(parent_dir / 'data/raw/train_traction_data.xlsx', index_col=0)
    diesel_traction_pass   = traction_data['kg diesel / pkm'].to_dict()
    electric_traction_pass = traction_data['kWh / pkm'].to_dict()
    diesel_traction_good   = traction_data['kg diesel / tkm'].to_dict()
    electric_traction_good = traction_data['kWh / tkm'].to_dict()
    return diesel_traction_pass, electric_traction_pass, diesel_traction_good, electric_traction_good


def treat_rail_transport(database, biosphere3, rail_fossil_reduction_factor, altered_activities,synfuel_split_dict, synfuel_subdb, identifiers, synfuel_dict, not_electrifiable_fuels, emission_factors_dict):
    """
    Replaces diesel trains with electric (overhead line) ones (freight)
    
    Replaces diesel input with electricity (passenger)
    
    Arguments:  database:                     Database to be manipulated
                biosphere3:                   Biosphere3 database
                rail_fossil_reduction_factor: % of defossilization, scalar
                altered_activities:           list of altered activities

    Return:
        updated list of altered activities
    """
    print("Electrifying rail transport.")

    #Get train traction
    diesel_traction_pass, electric_traction_pass, diesel_traction_good, electric_traction_good = get_train_traction_data()
    
    if rail_fossil_reduction_factor <= 1:
        # freight rail transport
        for market in [act for act in database
                       if 'market for transport, freight' in act['name']
                          and 'train' in act['name']
                       ]:
            not_electric_sum = 0
            reduction_amount = 0
            if 'market for transport, freight train' == market['name']:
                for exc in market.technosphere():
                    if any(keyword in exc.input['name'] for keyword in ['diesel', 'steam']):
                        not_electric_sum += exc['amount']
                        reduction_amount += exc['amount'] - (exc['amount'] * rail_fossil_reduction_factor)
                        exc['amount'] *= rail_fossil_reduction_factor
                        exc.save()
                for exc in market.technosphere():
                    if 'transport, freight train, electricity' == exc.input['name']:
                        exc['amount'] += not_electric_sum * (1 - rail_fossil_reduction_factor)
                        not_electric_sum = 0
                        exc.save()
                if not_electric_sum != 0:
                    new_train = ''
                    for el_train in [act for act in database
                                     if 'transport, freight train, electricity' in act['name']
                                        and market['location'] == act['location']
                                     ]:
                        new_train = el_train
                    if new_train == '':
                        for el_train in [act for act in database
                                         if 'transport, freight train, electricity' in act['name']
                                            and 'RoW' == act['location']
                                         ]:
                            new_train = el_train
                    market.new_exchange(input=new_train.key,
                                        name=new_train['name'],
                                        amount=not_electric_sum * (1 - rail_fossil_reduction_factor),
                                        unit='ton kilometer',
                                        type='technosphere').save()
                    market['treated']   =True   
                    market.save()
                    altered_activities = track_changes(market, altered_activities, 'scaling')
        
        #Electric freight trains            
        for activity in [act for act in database if 'transport, freight train, electricity' in act['name']
                          and not 'market' in act['name']]:
            
            altered_activities = defossilize_biosphere_flows(altered_activities, activity, biosphere3, 
                                                           rail_fossil_reduction_factor, False)
            altered_activities = track_changes(market, altered_activities, 'scaling')

            reduction_amount  = 0
            try:
                d_traction   = diesel_traction_good[activity["location"]]
                e_traction   = electric_traction_good[activity["location"]]
            except:
                d_traction   = diesel_traction_good["AV"] #take average
                e_traction   = electric_traction_good["AV"] #take average

            #scale down diesel consumption
            for exc in activity.technosphere():
                if any(keyword in exc.input['name'] for keyword in ['market for diesel']):
                    reduction_amount += exc['amount'] * (1 - rail_fossil_reduction_factor) / d_traction #unit: pkm
                    exc['amount'] *= rail_fossil_reduction_factor
                    exc.save()
            #scale up electricity consumption
            electricity_exchanges=[exc for exc in activity.technosphere()
                        if any(keyword in exc.input['name'] for keyword in ['market for electricity, high voltage'])]
            for exc in electricity_exchanges:
                    exc['amount'] += (reduction_amount * e_traction)/len(electricity_exchanges)
                    exc.save()
            activity['treated']   =True   
            activity.save()
            altered_activities = track_changes(activity, altered_activities, 'scaling')
        
        # passenger rail transport
        for activity in [act for act in database
                           if 'transport, passenger train' in act['name']
                              and not 'market' in act['name']
                           ]:
            altered_activities = defossilize_biosphere_flows(altered_activities, activity, biosphere3, 
                                                               rail_fossil_reduction_factor, False)
            reduction_amount  = 0
            try:
                d_traction   = diesel_traction_pass[activity["location"]]
                e_traction   = electric_traction_pass[activity["location"]]
            except:
                d_traction   = diesel_traction_pass["AV"] #take average
                e_traction   = electric_traction_pass["AV"] #take average
        
            #scale down diesel consumption
            for exc in activity.technosphere():
                if any(keyword in exc.input['name'] for keyword in ['market for diesel']):
                    reduction_amount += exc['amount'] * (1 - rail_fossil_reduction_factor) / d_traction #unit: pkm
                    exc['amount'] *= rail_fossil_reduction_factor
                    exc.save()
            #scale up electricity consumption
            electricity_exchanges=[exc for exc in activity.exchanges()
                            if any(keyword in exc.input['name'] for keyword in ['market for electricity, high voltage'])]
            for exc in electricity_exchanges:
                    exc['amount'] += (reduction_amount * e_traction)/len(electricity_exchanges)
                    exc.save()
            activity['treated']   =True   
            activity.save()
            altered_activities = track_changes(activity, altered_activities, 'scaling')

        # Diesel or steam trains
        for activity in [act for act in database if ('transport, freight train, steam' in act['name'] or 'transport, freight train, diesel' in act['name'])
                              and not 'market' in act['name']]:
            mod_fossil_reduction_factor_dict = get_modified_fossil_reduction_factor(activity, rail_fossil_reduction_factor,
                                                                                    identifiers, synfuel_dict,
                                                                                    not_electrifiable_fuels,
                                                                                    emission_factors_dict, synfuel_split_dict)
            altered_activities = defossilize_biosphere_flows(altered_activities, activity, biosphere3, 
                                                         rail_fossil_reduction_factor, True, mod_fossil_reduction_factor_dict)
            altered_activities = replace_fuel(altered_activities, activity, rail_fossil_reduction_factor, synfuel_subdb, 
                                                                          synfuel_split_dict, vehicles)
            
            activity['treated']=True
            activity.save()
    print("Rail transport electrified.")            
    return altered_activities


def treat_water_transport(database, biosphere3, waterway_fossil_reduction_factor, altered_activities, synfuel_split_dict, synfuel_subdb, identifiers, synfuel_dict, not_electrifiable_fuels, emission_factors_dict):
    """

    Defossilization of ship transport by replacing fossil fuels with synfuels.
    
    Arguments: database:                         Database to be manipulated
               synfuel_database:                 Database with synfuel production processes
               waterway_fossil_reduction_factor: % of defossilization of ships, scalar
               altered_activities:               list of altered activities
               
    Returns:
              altered_activities:                updated list of altered activities

    """
    print("Defossilizing water transport.") 
    if waterway_fossil_reduction_factor <= 1:
        water_freight_acts=[act for act in database
                            if ("transport, freight, sea" in act["name"]
                                or "transport, freight, inland waterways" in act["name"])
                                and not "market" in act["name"]
                                and not "reefer" in act["name"]]
        
        for water_act in water_freight_acts:
            mod_fossil_reduction_factor_dict = get_modified_fossil_reduction_factor(water_act, waterway_fossil_reduction_factor,
                                                                                    identifiers, synfuel_dict,
                                                                                    not_electrifiable_fuels,
                                                                                    emission_factors_dict, synfuel_split_dict)
            altered_activities = defossilize_biosphere_flows(altered_activities, water_act, biosphere3, 
                                                         waterway_fossil_reduction_factor, True, mod_fossil_reduction_factor_dict)
            altered_activities = replace_fuel(altered_activities, water_act, waterway_fossil_reduction_factor, synfuel_subdb, 
                                                                          synfuel_split_dict, vehicles)
            water_act['treated']=True
            water_act.save()
    print("Water transport defossilized.")         
    return altered_activities

def substitute_fuels_category(synfuel_names):
    biogen, syngen = False, False
    for synfuel in synfuel_names:
        if 'bio' in synfuel or 'charcoal' in synfuel or 'petrol, synthetic, E' in synfuel:
            biogen=True
        if 'synthetic' in synfuel:
            syngen=True
    if biogen and not syngen:
        return 'biogen'
    elif syngen and not biogen:
        return 'syngen'
    else:
        return 'both'

def treat_air_transport(database, biosphere3, aircraft_fossil_reduction_factor, altered_activities, synfuel_split_dict, synfuel_subdb, identifiers, synfuel_dict, not_electrifiable_fuels, emission_factors_dict):
    """
    
    Defossilization of aircraft transport by replacing fossil fuels with synfuels.
    
    Arguments: database:                         Database to be manipulated
               aircraft_fossil_reduction_factor: % of defossilization of ships, scalar
               altered_activities:               list of altered activities
               
    Returns:
              altered_activities:                updated list of altered activities

    
    """
    print("Defossilizing air transport.")  
    #find all air transport processes
    airtransport_acts=[act for act in database if ("transport, freight, aircraft" in act["name"] 
                                                   or "transport, passenger aircraft" in act["name"]
                                                   or "transport, helicopter" in act['name'])
                                                   and not "market" in act["name"]
                                                   and not "reefer" in act["name"]]
    for airtransport_act in airtransport_acts:
        mod_fossil_reduction_factor_dict = get_modified_fossil_reduction_factor(airtransport_act, aircraft_fossil_reduction_factor,
                                                                                    identifiers, synfuel_dict,
                                                                                    not_electrifiable_fuels,
                                                                                    emission_factors_dict, synfuel_split_dict)
        altered_activities = defossilize_biosphere_flows(altered_activities, airtransport_act, biosphere3, 
                                                         aircraft_fossil_reduction_factor, True, mod_fossil_reduction_factor_dict)
        altered_activities = replace_fuel(altered_activities, airtransport_act, aircraft_fossil_reduction_factor,
                                                      synfuel_subdb, synfuel_split_dict, vehicles)
        airtransport_act['treated']=True
        airtransport_act.save()
    print("Air transport defossilized.")
    return altered_activities
                             
def treat_road_transport(database, biosphere3, synfuel_split_dict, passenger_car_type_split, fossil_reduction_factor, altered_activities, synfuel_subdb, identifiers, synfuel_dict, not_electrifiable_fuels, emission_factors_dict):
    """
    
    """
    print("Defossilize ICEVs")
    #find all ICE passenger car transport processes
    EV_total = passenger_car_type_split['FCEV']+passenger_car_type_split['BEV']
    if passenger_car_type_split['ICE']<1:                        
        print("Defossilizing internal combustion cars.")                    
        ICE_acts=[act for act in database if (('transport, passenger car' in act['name']
                                and 'size' in act['name'])
                                or 'transport, freight, light commercial vehicle' in act['name']
                                or 'transport, regular bus' in act['name']
                                or 'transport, freight, lorry ' in act['name']
                                or 'transport, passenger, motor scooter' in ['name']
                                or 'transport, passenger coach' in act['name'])
                                and 'market' not in act['name']
                                and 'reefer' not in act['name']
                                and 'fatty acid methyl ester 100%' not in act['name']]
        
        synfuel_subdb= [[act for act in database if synfuel_name==act['name']][0] 
                                            for synfuel_name in flatten(list(synfuel_dict.values()))]

        #Reduce fossil fuel input and add synfuel
        for ICE_act in ICE_acts:
            mod_fossil_reduction_factor_dict = get_modified_fossil_reduction_factor(ICE_act, fossil_reduction_factor,
                                                                                    identifiers, synfuel_dict,
                                                                                    not_electrifiable_fuels,
                                                                                    emission_factors_dict, synfuel_split_dict)
            altered_activities = defossilize_biosphere_flows(altered_activities, ICE_act, biosphere3, 
                                                         fossil_reduction_factor, True, mod_fossil_reduction_factor_dict)
            altered_activities = replace_fuel(altered_activities, ICE_act, fossil_reduction_factor, synfuel_subdb, synfuel_split_dict, vehicles)
            ICE_act['treated']=True
            ICE_act.save()
    print("Replaced fossil fuel with syn- and biofuels in ICEVs.")
    
    #scale passenger car transport
    transport_passenger_cars = [act for act in database if 'transport, passenger car'==act['name']]
    electric_car_transports = [act for act in database if 'transport, passenger car' in act['name']
                                                                 and ('battery' in act['name'] 
                                                                  or 'fuel cell' in act['name'])]
    for transport_passenger_car in transport_passenger_cars:
        ICE_exc = [exc for exc in transport_passenger_car.technosphere() 
                       if exc.input['name']=='market for transport, passenger car with internal combustion engine']
        ex_amount = sum([exc.amount for exc in ICE_exc])
        for exc in ICE_exc: #scale down 'market for transport, passenger car with internal combustion engine'
            exc['amount']*=fossil_reduction_factor
            exc.save()
            
        #create new market : 'market for transport, passenger car, electric'
        market_name  = 'market for transport, passenger car, electric'
        product_name = 'transport, passenger car, electric'
        market_code  = uuid.uuid4().hex
        
        try:
            ecar_market= database.new_activity(code=market_code,
                                               name=market_name,
                                               unit=transport_passenger_car['unit'],
                                               type='process',
                                               location=transport_passenger_car['location'])
            ecar_market.save()
            ecar_market['production amount']   = 1.0
            ecar_market['reference product'] = product_name
            ecar_market.save()
        except:
            ecar_market = database.get(market_code)
            print(ecar_market," already in database.")
        
        #get size share
        ICE_markets   = [exc.input for exc in ICE_exc]
        EURO_exchanges =flatten([flatten([list(exc.input.technosphere()) for exc in ICE_market.technosphere()]) 
                                         for ICE_market in ICE_markets])
        EURO_split = np.array([exc.amount for exc in EURO_exchanges])
        sizes = ['small', 'medium', 'large']
        
        lists=flatten([[list(exc.input.technosphere()) for exc in list(input.technosphere())] 
                                                  for input in [exc1.input for exc1 in EURO_exchanges]])
        size_shares= np.array([[sum([exc.amount for exc in list if size in exc.input['name']]) for size in sizes] for list in lists])
        size_share=sum(size_shares*EURO_split)
   
        amounts = []
       
        for electric_car_transport in electric_car_transports:
            current_size_share = [share for share in size_share 
                                      if sizes[list(size_share).index(share)] in electric_car_transport['name'].lower()][0]
            if 'battery' in electric_car_transport['name']:
                type_split = passenger_car_type_split['BEV']/EV_total
            elif 'fuel cell' in electric_car_transport['name']:
                type_split = passenger_car_type_split['FCEV']/EV_total
            else:
                raise Exception("This is not an electric car: ", electric_car_transport)
            try:
                amount = current_size_share*type_split
            except:
                raise Exception("Cannot multiply ", current_size_share, type_split)
            amounts.append(amount)
        amounts = [amount/sum(amounts) for amount in amounts] #balance to 1
                                  
        add_technosphere_flows_to_activity(ecar_market, electric_car_transports, amounts) #add inputs to e-car market
        add_technosphere_flows_to_activity(transport_passenger_car, [ecar_market], [ex_amount*(1-fossil_reduction_factor)]) #add e-car market

        altered_activities = track_changes(ecar_market, altered_activities, 'scaling')
        altered_activities = track_changes(transport_passenger_car, altered_activities, 'scaling')
        
    print("Added markets for transport, passenger car, electric.")
    print("ICEVs defossilized.") 
    return altered_activities

def treat_transport(database, biosphere3, car_year, truck_year, lorry_type_split, passenger_car_type_split, 
                    road_fossil_reduction_factor,  rail_fossil_reduction_factor, waterway_fossil_reduction_factor, 
                    aircraft_fossil_reduction_factor, synfuel_dict, fossil_identifiers, not_electrifiable_fuels, 
                    emission_factors_dict, synfuel_split_dict, ei_version, altered_activities):
    
    """
    Function carries out defossilization of each transport mode: passenger cars, lorries, trains, ships, aircrafts.
    
    Args:
            database:                               Database to be manipulated
            biosphere3 :                            Biosphere3 database
            car_year:                               Year of scenario for car creation
            truck_year:                             Year of scenario for truck creation
            lorry_type_split: split of lorry types: Batteries, fuel cell, etc.
            passenger_car_type_split:               Split of car types: batteries, fuel cell, etc.
            fossil_reduction_factor:                0 means full defossilization, 1 means unaltered
            waterway_fossil_reduction_factor:       Like fossil_reduction_factor for ships
            aircraft_fossil_reduction_factor:       Like fossil_reduction_factor for aircrafts and helicopters
            altered_activities:                     Dictionary of altered activities for documentation
            synfuel_split_dict:                     Split for fuel replacement, synthetic and bio fuels
            ei_version:                             Version of ecoinvent, e.g. "ecoinvent 3.8 cutoff"
    Returns:
            
            altered_activities:                     Updated dictionary of altered activities
    
    """
    global vehicles
    vehicles = import_vehicles()
    
    synfuel_subdb = [act for act in database if act['name'] in list(set(flatten(list(synfuel_dict.values()))))]
    
    altered_activities, market_code_dict = electric_lorry_market_setup(database           = database,
                                                                       lorry_type_split   = lorry_type_split,
                                                                       altered_activities = altered_activities
                                                                      )
    
    altered_activities = scale_lorry_markets(database           = database,
                                             lorry_type_split   = lorry_type_split,
                                             code_dict          = market_code_dict,
                                             altered_activities = altered_activities
                                            )
    
    altered_activities = treat_rail_transport(database                     = database,
                                              biosphere3                   = biosphere3,
                                              rail_fossil_reduction_factor = rail_fossil_reduction_factor,
                                              altered_activities           = altered_activities, 
                                              synfuel_split_dict           = synfuel_split_dict,
                                              synfuel_subdb                = synfuel_subdb,
                                              identifiers                  = fossil_identifiers,
                                              synfuel_dict                 = synfuel_dict,
                                              not_electrifiable_fuels      = not_electrifiable_fuels,
                                              emission_factors_dict        = emission_factors_dict
                                             )
    
    altered_activities = treat_water_transport(database,
                                               biosphere3,
                                               waterway_fossil_reduction_factor, 
                                               altered_activities,
                                               synfuel_split_dict,
                                               synfuel_subdb,
                                               fossil_identifiers,
                                               synfuel_dict,
                                               not_electrifiable_fuels,
                                               emission_factors_dict
                                              )
                                                             
    altered_activities = treat_air_transport(database                         = database,
                                             biosphere3                       = biosphere3,
                                             aircraft_fossil_reduction_factor = aircraft_fossil_reduction_factor,
                                             altered_activities               = altered_activities,
                                             synfuel_split_dict               = synfuel_split_dict,
                                             synfuel_subdb                    = synfuel_subdb,
                                             identifiers                      = fossil_identifiers,
                                             synfuel_dict                     = synfuel_dict,
                                             not_electrifiable_fuels          = not_electrifiable_fuels,
                                             emission_factors_dict            = emission_factors_dict
                                            ) 
    
    altered_activities = treat_road_transport(database                 = database,
                                              biosphere3               = biosphere3,
                                              synfuel_split_dict       = synfuel_split_dict, 
                                              passenger_car_type_split = passenger_car_type_split,
                                              fossil_reduction_factor  = road_fossil_reduction_factor,
                                              altered_activities       = altered_activities,
                                              synfuel_subdb            = synfuel_subdb,
                                              identifiers              = fossil_identifiers,
                                              synfuel_dict             = synfuel_dict,
                                              not_electrifiable_fuels  = not_electrifiable_fuels,
                                              emission_factors_dict    = emission_factors_dict
                                             )
    
    
    print("-----------------------")
    print("Transport defossilized.")
    print("-----------------------")
    return altered_activities
