import numpy as np
from checks_and_balances import track_changes
from datetime import datetime
from heat import indices
import uuid
from utils import progress_bar, flatten, regionalise_activity, import_input_map

def roof_pv_market_setup(database, location, transformation_losses, altered_activities):
    """
    This creates a market for  electricity produced by a mix of photovoltaic activities.

    For the selected location a new market activity is created that combines all roof mounted photovoltaic electrical
    energy productions (or RoW ones if there are none for the specific locations).  The losses for the conversion
    from (low voltage) PV production to the voltage level of the high voltage grid is included.

    Args:
        database: the database which will be treated
        location: the location which is being treated
        transformation_losses: the amount of losses considered for bringing PV power up to the high voltage grid
        altered_activities: dictionary where newly created and altered activities are stored

    Returns:
        Updated dictionary of altered activities
    """
    if len([act for act in database if
                'Market for roof mounted photovoltaic production' in act['name'] and location == act['location']])>=1:
        print('----')
        act = [act for act in database if
                'Market for roof mounted photovoltaic production' in act['name'] and location == act['location']][0]
        print(act['name'], ' is already present')
        print('----')
        return altered_activities, act['code']

    market_name = "Market for roof mounted photovoltaic production in " + location
    market_code = uuid.uuid4().hex
    
    # Create market
    pv_market= database.new_activity(code=market_code,
                                   name=market_name,
                                   unit='kilowatt hour',
                                   type='process',
                                   location=location)
    pv_market.save()
    pv_market["reference product"]= 'electricity, low voltage'
    pv_market["production amount"]= 1.0
    pv_market["comment"]= 'Pooling of all roof PV production in {}. Transformation is accounted for with transformation losses ({}).'.format(location, transformation_losses)
    pv_market.save()
    altered_activities = track_changes(pv_market, altered_activities, 'activity creation')
   
    # retrieve roof mounted pv sources
    roof_pv_list = [act for act in database if 'electricity production, photovoltaic' in act['name']
                                           and 'roof' in act['name']
                                           and location == act['location']]

    # Rest of World shall be used if non are available for the selected location
    if len(roof_pv_list) == 0:
        roof_pv_list = [act for act in database if 'electricity production, photovoltaic' in act['name']
                                           and 'roof' in act['name']
                                           and 'RoW' == act['location']]

    # populate market with  pv sources
    for roof_pv in roof_pv_list:
        pv_market.new_exchange(input=roof_pv,
                               name='electricity, low voltage',
                               amount=(1+transformation_losses) / len(roof_pv_list),
                               unit='kilowatt hour',
                               location=location,
                               type='technosphere',
                               flow=database.get(roof_pv[1])["flow"]).save()                             
    
    return altered_activities, market_code


def add_storage_to_pv_market(database, location, phi, numb_cycles, discharge_depth, 
                             nu_turnaround, d, nu_fuel_cell, db_dict, market_code, input_map, ei_version, altered_activities):
    """
    This adds storage to the pv market according to the specified ratio of storage type and technological input values. 
    It also creates market for PV including storage for low, medium and high voltage based on transformation processes to higher voltage
    levels.
    
    Args:
        database: the database which will be treated
        location: the location which is being treated
        phi: split of different storage options
        numb_cycles: Number of cycles for batteries
        discharge_depth: Discharge depth of battery
        nu_turnaround: Battery turnaround efficiency
        u: battery voltage
        db_dict: fast access representation of database
        altered_activities: dictionary where newly created and altered activities are stored

    Returns:
        the updated list of altered activities is returned
    """
    priorities =['RoW','GLO'] #if no match in location, search in RoW, else globally

    pv_and_stor_market_name = 'market for PV including storage in ' + location + ', low voltage'
    pv_and_stor_market_code = uuid.uuid4().hex
    battery_storage_name = 'electricity from battery storage in ' + location
    battery_storage_code = uuid.uuid4().hex

    if len([act for act in database if pv_and_stor_market_name in act['name'] and location == act['location']])>=1:
        print('----')
        act = [act for act in database if pv_and_stor_market_name in act['name'] and location == act['location']][0]
        print(act['name'], ' is already present in ', act['location'], 'The storage set up function has not been run.')
        print('----')
        return altered_activities, act['code']

    # create market for pv including storage
    pv_market_incl_storage = database.new_activity(code=pv_and_stor_market_code,
                                                   name=pv_and_stor_market_name,
                                                   unit='kilowatt hour',
                                                   type='process',
                                                   location=location)
    pv_market_incl_storage.save()
    pv_market_incl_storage["reference product"]= 'electricity, low voltage'
    pv_market_incl_storage["production amount"]= 1.0
    pv_market_incl_storage.save()

    altered_activities = track_changes(pv_market_incl_storage, altered_activities,'activity creation')

    #find transformation loss
    for act in [act for act in database if act["name"]=="electricity voltage transformation from high to medium voltage"
                                            and act["location"]==location]:
        exc=[exc for exc in act.exchanges() if exc.input["name"]=="market for electricity, high voltage"
                                               and exc.input["location"]==location][0]
        transformation_amount_high2med=exc.amount #finding the 1+losses in transformation

    for act in [act for act in database if act["name"]=="electricity voltage transformation from medium to low voltage"
                                            and act["location"]==location]:
        exc=[exc for exc in act.exchanges() if exc.input["name"]=="market for electricity, medium voltage"
                                               and exc.input["location"]==location][0]
        transformation_amount_med2low=exc.amount #finding the 1+losses in transformation

    # DIRECT SOLAR.
    direct_solar = 1
    for storage_type in phi:
        if storage_type not in ['pumped']:
            direct_solar -= phi[storage_type]
    pv_market_incl_storage.new_exchange(input=database.get(market_code).key,
                                        name='electricity, directly from PV production',
                                        amount=direct_solar,
                                        unit='kilowatt hour',
                                        location=location,
                                        type='technosphere').save()

    # BATTERY STORAGE.
    battery_storage_market = database.new_activity(code=battery_storage_code,
                                                   name=battery_storage_name,
                                                   unit='kilowatt hour',
                                                   location=location)
    battery_storage_market.save()
    battery_storage_market["reference product"]= 'electricity, from battery'
    battery_storage_market["production amount"]= 1.0
    battery_storage_market.save()
    altered_activities = track_changes(battery_storage_market, altered_activities, 'activity creation')
    # add the electricity tha flows into the battery storage
    battery_storage_market.new_exchange(input=database.get(market_code).key,
                                        name='electricity, directly from PV production',
                                        amount=1 / nu_turnaround,
                                        unit='kilowatt hour',
                                        location=location,
                                        type='technosphere').save()
    # add the battery cells needed for the battery storage
    for act in [act for act in database if
                'Battery cell, LFP' in act['name'] and 'GLO' in act['location']]:
        battery_cell_key = act.key

    battery_storage_market.new_exchange(input=battery_cell_key,
                                        name= database.get(battery_cell_key[1])['name'],
                                        amount=(1 / (numb_cycles * discharge_depth * nu_turnaround * d)),
                                        unit='kilogram',
                                        type='technosphere').save()
    
    pv_market_incl_storage.new_exchange(input=database.get(battery_storage_code).key,
                                        name='electricity, directly from PV production',
                                        amount=phi['battery'],
                                        unit='kilowatt hour',
                                        type='technosphere').save()
    
    #HYDROGEN STORAGE
    #creating "electricity from hydrogen storage"
    H2_key_dict = {'name': 'electricity from hydrogen storage in '+location,
                   'reference product': 'electricity, medium voltage',
                   'code': uuid.uuid4().hex,
                   'type':'process',
                   'location': location,
                   'unit': 'kilowatt hour',
               'production amount': 1.0}
    H2_storage= database.new_activity(**H2_key_dict)
    H2_storage.save()
    
    #get inputs
    
    #Fuel Cell Solid oxide
    SO_fuel_cell = database.get(input_map[ei_version]['SOFC'])
    SO_fuel_cell_exc_dict = {'input': SO_fuel_cell.key, 'name': SO_fuel_cell['name'], 'amount': 2*10**-7, 'uncertainty type':0,
                        'unit': SO_fuel_cell['unit'], 'location': location, 'type':'technosphere'}
    
    SO_maintenance = database.get(input_map[ei_version]['SOFC_maintenance'])
    SO_maintenance_exc_dict = {'input': SO_maintenance.key, 'name': SO_maintenance['name'], 'amount': 7.2*10**-7, 'uncertainty type':0,
                        'unit': SO_maintenance['unit'], 'location': location, 'type':'technosphere'}
    
    #Hydrogen refuelling station
    station = database.get(input_map[ei_version]['H_station'])
    station_exc_dict = {'input': station.key, 'name': station['name'], 'amount': 1.15*10**-7, 'uncertainty type':0,
                        'unit': station['unit'], 'location': location, 'type':'technosphere'}
    #Hydrogen, 700 bars
    hydrogen_25bar_base = database.get(input_map[ei_version]['H25bar2'])
    hydrogen_25bar, db_dict = regionalise_activity(hydrogen_25bar_base, location, database, db_dict, priorities)
    
    hydrogen_700bar_base = database.get(input_map[ei_version]['H700bar'])
    hydrogen_700bar, db_dict = regionalise_activity(hydrogen_700bar_base, location, database, db_dict, priorities) #regionalize hydrogen
    hydrogen_exc_dict  = {'input':(hydrogen_700bar['database'], hydrogen_700bar['code']), 'name': hydrogen_700bar['name'],
                           'amount': (1/39.4)/nu_fuel_cell, 'uncertainty type':0,
                        'unit': hydrogen_700bar['unit'], 'location': location, 'type':'technosphere'}
    
    self_exc_dict = {'input':(H2_storage['database'], H2_storage['code']), 'name': H2_storage['name'],
                           'amount': 1, 'uncertainty type':0, 'reference product': H2_storage['reference product'],
                        'unit': H2_storage['unit'], 'location': H2_storage['location'], 'type':'production'}
    
    #add exchanges
    exc_dicts = [self_exc_dict, station_exc_dict, hydrogen_exc_dict,
                 SO_fuel_cell_exc_dict, SO_maintenance_exc_dict]
    
    [H2_storage.new_exchange(**exc_dict).save() for exc_dict in exc_dicts]
    
    
    if phi['h2']>0:
        pv_market_incl_storage.new_exchange(input=(database.name, H2_key_dict['code']),
                                            name=H2_key_dict['name'],
                                            amount=phi['h2'],
                                            unit='kilowatt hour',
                                            location=location,
                                            type='technosphere').save()
        pv_market_incl_storage.save()
    altered_activities = track_changes(H2_storage, altered_activities, 'activity creation')
    
    #creating transformation processes low voltage - medium voltage
    voltage_transf_low2medium_name = 'electricity voltage transformation from low to medium voltage in ' + location
    voltage_transf_low2medium_code = uuid.uuid4().hex
    
    voltage_transf_low2medium = database.new_activity(code=voltage_transf_low2medium_code,
                                                      name=voltage_transf_low2medium_name,
                                                      unit='kilowatt hour',
                                                      type='process',
                                                      location=location)
    voltage_transf_low2medium.save()
    voltage_transf_low2medium["reference product"]= 'electricity, medium voltage'
    voltage_transf_low2medium["production amount"]= 1.0
    voltage_transf_low2medium.save()
    
    altered_activities = track_changes(voltage_transf_low2medium, altered_activities, 'activity creation')
   
    
    voltage_transf_low2medium.new_exchange(input=database.get(pv_market_incl_storage["code"]).key,
                                        name=pv_market_incl_storage["name"],
                                        amount=transformation_amount_med2low,
                                        unit='kilowatt hour',
                                        location=location,
                                        type='technosphere').save()
    
     # create market for pv including storage, medium voltage
    pv_and_stor_market_medvol_name = 'market for PV including storage in ' + location + ', medium voltage'
    pv_and_stor_market_medvol_code = uuid.uuid4().hex
    
    pv_market_incl_storage_medvol = database.new_activity( code=pv_and_stor_market_medvol_code,
                                                           name=pv_and_stor_market_medvol_name,
                                                           unit='kilowatt hour',
                                                           type='process',
                                                           location=location)
    pv_market_incl_storage_medvol.save()
    pv_market_incl_storage_medvol["reference product"]= 'electricity, medium voltage'
    pv_market_incl_storage_medvol["production amount"]= 1.0
    pv_market_incl_storage_medvol.save()
    
    pv_market_incl_storage_medvol.new_exchange(input=database.get(voltage_transf_low2medium_code).key,
                                                name=voltage_transf_low2medium_name,
                                                amount=1,
                                                unit='kilowatt hour',
                                                location=location,
                                                type='technosphere').save()
    
    altered_activities = track_changes(pv_market_incl_storage_medvol, altered_activities, 'activity creation')
    
    #creating transformation processes medium voltage - high voltage
    voltage_transf_med2high_name = 'electricity voltage transformation from medium to high voltage in ' + location
    voltage_transf_med2high_code = uuid.uuid4().hex
    
    voltage_transf_med2high = database.new_activity(       code=voltage_transf_med2high_code,
                                                           name=voltage_transf_med2high_name,
                                                           unit='kilowatt hour',
                                                           type='process',
                                                           location=location)
    voltage_transf_med2high.save()
    voltage_transf_med2high["reference product"]= 'electricity, high voltage'
    voltage_transf_med2high["production amount"]= 1.0
    voltage_transf_med2high.save()
    
    altered_activities = track_changes(voltage_transf_med2high, altered_activities, 'activity creation')
    
 
    voltage_transf_med2high.new_exchange(input=database.get(pv_and_stor_market_medvol_code).key,
                                          name=pv_and_stor_market_medvol_name,
                                        amount=transformation_amount_high2med,
                                          unit='kilowatt hour',
                                      location=location,
                                          type='technosphere').save()
    
    # create market for pv including storage, high voltage
    pv_and_stor_market_highvol_name = 'market for PV including storage in ' + location + ', high voltage'
    pv_and_stor_market_highvol_code = uuid.uuid4().hex
    
    pv_market_incl_storage_highvol = database.new_activity( code=pv_and_stor_market_highvol_code,
                                                            name=pv_and_stor_market_highvol_name,
                                                            unit='kilowatt hour',
                                                            type='process',
                                                            location=location)
    pv_market_incl_storage_highvol.save()
    pv_market_incl_storage_highvol["reference product"]= 'electricity, high voltage'
    pv_market_incl_storage_highvol["production amount"]= 1.0
    pv_market_incl_storage_highvol.save()
    
    pv_market_incl_storage_highvol.new_exchange(input=database.get(voltage_transf_med2high_code).key,
                                                 name=voltage_transf_med2high_name,
                                               amount=1-phi['pumped'],
                                                 unit='kilowatt hour',
                                             location=location,
                                                 type='technosphere').save()
    
    #HYDRO STORAGE
    if phi['pumped']>0:
        hydro_key = ""
        for act in [act for act in database if 'pumped storage' in act['name'] and location == act['location']]:
            hydro_key = act.key
        if hydro_key == "":
            for act in [act for act in database if 'pumped storage' in act['name'] and "RoW" == act['location']]:
                hydro_key = act.key

        pv_market_incl_storage_highvol.new_exchange(input=hydro_key,
                                            name='electricity from pumped hydro power',
                                            amount=phi['pumped'],
                                            unit='kilowatt hour',
                                            location=location,
                                            type='technosphere').save()
    
    altered_activities = track_changes(pv_market_incl_storage_highvol, altered_activities, 'activity creation')
    return altered_activities, pv_and_stor_market_highvol_code

def not_null_split_only(activities, electricity_split):
    """
    Filters activities, where share in scaled market not zero.
    """
    for idx in indices(list(electricity_split.values()), 0, '=='):
        keywords = electricity_split[list(electricity_split.keys())[idx]]
        activities=[act for act in activities if not any([keyword in act['name'] for keyword in keywords])]        
    return activities

def scale_exchanges(database, location, fossil_reduction_factor, fossil_identifiers, electricity_split, pv_and_stor_market_code, altered_activities):
    """
    Scaling down fossil electricity sources in electricity markets and adding and scaling up renewable ones.
    
    Args:
        database: database to be treated
        location: location of electricity markets
        fossil_reduction_factor: 0 means complete fossil phase-out, 1 all fossils remain
        electricity_split: dictionary of electricity sources and respective shares for adding them
        altered_activities: dictionary of altered activities (for documentation)
        
    returns:
        altered_activities: updated dictionary of altered activities
    """
    electricity_productions = [act for act in database if 'electricity production' in act['name']
                                               and 'heat and power co-generation' in act['name']
                                               and act['location']==location
                                               and 'kilowatt hour' in act['unit']
                                              ]
    
    electricity_productions = not_null_split_only(electricity_productions, electricity_split) #only productions with split > 0
    
    for act in [act for act in database
            if ('market for electricity, high voltage' in act['name']
            or 'electricity, high voltage, aluminium industry' in act['name']
            or 'electricity production, high voltage, cobalt industry' == act['name']
            or 'heat and power co-generation' in act['name']
            or 'electricity production, natural gas, aluminium industry' in act['name']
            or 'electricity production, coal, aluminium industry' in act['name']
            or 'electricity market for fuel preparation' in act['name']
            or 'electricity market for energy storage production' in act['name']    
            or 'production mix' in act['name']
            or 'residual mix' in act['name']
            or 'European attribute mix' in act['name']
            )
            and "kilowatt hour"==act['unit']  
            and location == act['location']
                   ]:
        supply_shortage = 0
        
        for exchange in act.technosphere():
            source_act = exchange.input

            #  reduce fossil based electricity
            if any(keyword in source_act['name'] for keyword in fossil_identifiers) and source_act["unit"]=="kilowatt hour":
                ex_amount = exchange['amount']
                new_ex_amount = exchange['amount'] * fossil_reduction_factor
                exchange['amount'] = new_ex_amount
                exchange.save()

                if (ex_amount - new_ex_amount) != 0:
                    supply_shortage += ex_amount - new_ex_amount

        if supply_shortage!=0:
            voltage=','.join(source_act["reference product"].split(',')[:2])
            
            if electricity_productions==[]:
                old_location = location
                location = 'RoW' #if no electricity production in that location, take RoW electricity production
                sub_database = database
            else:
                sub_database = electricity_productions
            
            #wind onshore
            wind_on_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and "electricity production" in act["name"]
                          and "onshore" in act["name"]
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #wind offshore
            wind_off_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and "electricity production" in act["name"]    
                          and "offshore" in act["name"]
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #hydro
            hydro_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and "electricity production" in act["name"]
                          and "hydro" in act["name"]
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #geothermal
            geothermal_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and "electricity production" in act["name"]
                          and "geothermal" in act["name"]
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #biomass
            biomass_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and ("electricity production" in act["name"]
                          or   "heat and power co-generation" in act["name"])
                          and ("bio" in act["name"]
                          or "wood" in act["name"])    
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #nuclear
            nuclear_acts=[act for act in sub_database
                          if act["unit"]=="kilowatt hour"
                          and "electricity production" in act["name"]
                          and "nuclear" in act["name"]   
                          and act["location"]==location
                          and act["reference product"]==voltage]
            
            #concentrated solar power
            solar_acts=[act for act in sub_database
                        if 'electricity production, solar' in act['name']
                        and (act["location"]==location or act["location"]=='RoW')]
            
            if electricity_productions==[]: #back to original location
                location = old_location
            
            #photovoltaic
            pv_market = database.get(pv_and_stor_market_code)
            
            subs_acts=[[pv_market], wind_on_acts, wind_off_acts, hydro_acts, geothermal_acts, biomass_acts, nuclear_acts, solar_acts]

            
            if flatten(subs_acts)==[]: #if there are no electricity production processes (e.g. RER), take market group
                try:
                    market_group = [act for act in database if 'market group for '+voltage==act['name']
                                                          and act['location']==location][0]
                except:
                    if 'IN' in location:
                        market_group = [act for act in database if 'market group for '+voltage==act['name']
                                                          and act['location']=='IN'][0]
                    else:
                        market_group = [act for act in database if 'market group for '+voltage==act['name']
                                                          and act['location']=='GLO'][0]
                act.new_exchange(input=market_group.key,
                                     amount=supply_shortage,
                                     unit=market_group['unit'],
                                     type='technosphere').save()

                          
            #balance electricity split
            empty=sum(np.multiply([act==[] for act in subs_acts], list(electricity_split.values()))) #True if empty list of acts in mode
            balanced_vals=np.multiply([act!=[] for act in subs_acts]/(1-empty), list(electricity_split.values())) #balance split to 100%
            electricity_split={ele: balanced_vals[list(electricity_split.keys()).index(ele)] for ele in electricity_split} #save

            #add other modes
            for mode in list(electricity_split.keys()): #"wind", "hydro", "biomass" ...
                mode_split=electricity_split[mode]*supply_shortage #e.g. 50% for "hydro"
                if mode_split!=0:
                    mode_acts=subs_acts[list(electricity_split.keys()).index(mode)] #e.g. hydro_acts
                    for mode_act in mode_acts: #add exchanges
                        if np.isnan(mode_split/len(mode_acts)):
                            raise Exception('amount is nan', mode_split, len(mode_acts))
                        act.new_exchange(input=mode_act.key,
                                         amount=mode_split/len(mode_acts),
                                         unit="kilowatt hour",
                                         type='technosphere').save()
                          
        altered_activities = track_changes(act, altered_activities, 'scaling')
    return altered_activities
    
def check_all_non_electricity_activities(database, fossil_reduction_factor, fossil_identifiers, altered_activities):
    #check all non-electricity-activities in location for fossil electricity inputs and substitute with local electricity market
    for act in [act for act in database if 'kilowatt hour'!=act['unit']]:    
        altered_activities = substitute_electricity_in_activity(database, act, fossil_reduction_factor, fossil_identifiers, altered_activities)
    return altered_activities

def substitute_electricity_in_activity(database, act, fossil_reduction_factor, fossil_identifiers, altered_activities):
    """
    Some processes do not have electricity markets as input but some specific fossil electricity sources. Here, these are substituted with the electricty market.
    
    Args:
        database: database to be treated
        act: activity
        fossil_reduction_factor: 0 means complete fossil phase-out, 1 all fossils remain
        altered_activities: dictionary of altered activities (for documentation)
        
    Returns:
        altered_activities: updated dictionary of altered activities (for documentation)
    """
    #Selecting fossil electricity sources in activity
    fossil_exchanges=[exc for exc in act.technosphere() 
                              if any(identifier in exc.input['name'] for identifier in fossil_identifiers)
                                and exc.input['unit']=='kilowatt hour'
                                 and exc.amount !=0]
    
    location = act['location']
    for fossil_exchange in fossil_exchanges:
        ex_amount = fossil_exchange['amount']

        ref_prod = ','.join(fossil_exchange.input['reference product'].split(',')[:2]) #e.g. low voltage
        
        try: #get local electricity market
            renew_act=[act for act in database if act['location']==location
                          and act['reference product']==ref_prod
                          and ('market for '+ref_prod in act['name']
                          or 'market group for '+ref_prod in act['name'])  
                          and act['unit']=='kilowatt hour'
                          and not 'industry' in act['name']
                          and not 'mix' in act['name']][0]
        except: #if no local electricity market: take global market
            renew_act=[act for act in database if act['location']=='GLO'
                                          and act['name']=='market group for '+ref_prod
                                          and ref_prod in act['reference product']
                                          and act['unit']=='kilowatt hour'][0]
        #Add electricity market
        act.new_exchange(input=renew_act.key,
                     amount=ex_amount*(1-fossil_reduction_factor),
                     unit="kilowatt hour",
                     type='technosphere').save()
        #Scale down fossil input
        fossil_exchange['amount']*=fossil_reduction_factor
        fossil_exchange.save()     
    altered_activities = track_changes(act, altered_activities, 'scaling')
    return altered_activities

def check_all_electricity_activities_where_no_markets(database, fossil_reduction_factor, fossil_identifiers, market_locations, altered_activities):
    """
    Selecting all electricity-providing processes that do not have an electricity market and defossilizing consumers.
    
    Args:
        database:                database to treat
        locations:               all locations with electricity markets
        fossil_reduction_factor: 0 means complete fossil phase-out, 1 all fossils remain
        altered_activities:      dictionary of altered activities (for documentation)
    Returns:
        altered_activities:      updated dictionary of altered activities (for documentation)
    
    """
    print("Scaling processes in locations without electricity markets.")
    all_locations    = set([act['location'] for act in database])
    rest_locations = all_locations.difference(set(market_locations))
    print("Found ", len(rest_locations), " to treat.")
    count=1
    for location in list(rest_locations):
        progress_bar(count, len(list(rest_locations)), location)
        for act in [act for act in database if ('market for electricity, high voltage' in act['name']
                            or 'aluminium industry' in act['name']
                            or 'cobalt industry' in act['name']                
                            or 'heat and power co-generation' in act['name']
                            or 'electricity market for fuel preparation' in act['name']
                            or 'electricity market for energy storage production' in act['name']    
                            or  'production mix' in act['name']
                            or 'residual mix' in act['name']
                            or 'European attribute mix' in act['name']
                            )
                            and "kilowatt hour"==act['unit']  
                            and location == act['location']]:
            altered_activities = substitute_electricity_in_activity(database, act, fossil_reduction_factor, fossil_identifiers, altered_activities)
        count+=1
    return altered_activities

def treat_electricity_markets(database, locations, transformation_losses, phi, numb_cycles, discharge_depth, ei_version,
                              nu_turnaround, d, nu_fuel_cell, fossil_reduction_factor, fossil_identifiers, altered_activities, electricity_split, scale_non_market_locations=True):
    """
    Defossilizing all electricity markets and and consumers of fossil-based electricity sources.
    
    Args:
        database:                Database to be treated
        locations:               All locations to be treated
        transformation_losses:   Transformation losses between low and medium, and medium and high voltage
        phi:                     Split of different storage options
        numb_cycles:             Number of cycles for batteries
        discharge_depth:         Discharge depth of battery
        nu_turnaround:           Battery turnaround efficiency
        u:                       Battery voltage
        fossil_reduction_factor: 0 means complete fossil phase-out, 1 all fossils remain
        altered_activities:      dictionary of altered activities (for documentation)
        electricity_split:       dictionary of electricity sources and respective shares for adding them
        
    Returns:
        altered_activities:      updated dictionary of altered activities (for documentation)
    """
    print("Treating electricity markets.")
    
    db_dict = [{'name': act['name'], 'product':act['reference product'],'unit' :act['unit'],
                        'code': act['code'], 'location': act['location']} for act in database]
    
    input_map = import_input_map()
    
    if len(locations) == 0:
        print('No locations given for electricity markets.')
        return altered_activities
    if fossil_reduction_factor == 1:
        print('Fossil reduction factor for electricity is 1, thus no changes in the electricity markets are made.')
        return altered_activities
    count=1
    for location in locations:
        progress_bar(count , len(locations), location)
        altered_activities, market_code             = roof_pv_market_setup(database,
                                                                           location,
                                                                           transformation_losses,
                                                                           altered_activities)
        altered_activities, pv_and_stor_market_code = add_storage_to_pv_market(database, location, phi,
                                                                               numb_cycles, discharge_depth,
                                                                               nu_turnaround, d, nu_fuel_cell, db_dict,
                                                                               market_code, input_map, ei_version, altered_activities)
        altered_activities = scale_exchanges(database, location, fossil_reduction_factor, fossil_identifiers,
                                                 electricity_split, pv_and_stor_market_code, altered_activities)
        count+=1
    
    
    if len(locations)>1 and scale_non_market_locations: 
        altered_activities = check_all_non_electricity_activities(database, fossil_reduction_factor, fossil_identifiers, altered_activities)

        altered_activities = check_all_electricity_activities_where_no_markets(database, fossil_reduction_factor,
                                                                               fossil_identifiers, locations, altered_activities)
    
    print("--------------------")
    print("Electricity defossilized!")
    print("--------------------")
    return altered_activities
