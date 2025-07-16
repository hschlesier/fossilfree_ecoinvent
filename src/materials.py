import bw2data as bd
from checks_and_balances import track_changes
import itertools
import numpy as np
import json
import uuid
from transport import import_synfuel_dict
import math
from utils import flatten, progress_bar, adjust_uncertainty, defossilize_biosphere_flows, fossil_to_nonfossil_biosphere_flows, add_technosphere_flows_to_activity, get_fuel_replacement_split, import_emission_factors, get_modified_fossil_reduction_factor, replace_fuel

def treat_other_processes(database, biosphere3, fossil_reduction_factor, synfuel_split_dict,electricity_locations,
                    synfuel_dict, emission_factors_dict, fossil_identifiers,
                    not_electrifiable_fuels, electrifiable_processes, not_electrifiable_processes,
                    fossil_refinery_processes, grouped_locations, altered_activities):
    """
    Defossilizises all activities that have fossil fuels as inputs.
    
    Args:
            database:                   database to treat
            biosphere3:                 biosphere3 database
            fossil_reduction_factor:    0 complete phase-out, 1 unaltered
            synfuel_split_dict:         split between bio and synthetic fuels
            altered_activities:         dictionary of altered activities (for documentation)
    Returns:
            altered_activities:         updated dictionary of altered activities
    
    """
    
    print("Defossilizing several processes with fossil fuel input.")
    if fossil_reduction_factor<1:
        altered_activities = treat_fossil_consumers(database,
                                                    biosphere3,
                                                    fossil_reduction_factor,
                                                    synfuel_split_dict,
                                                    electricity_locations,
                                                    emission_factors_dict,
                                                    synfuel_dict,
                                                    fossil_identifiers,
                                                    not_electrifiable_fuels,
                                                    electrifiable_processes,
                                                    not_electrifiable_processes,
                                                    fossil_refinery_processes,
                                                    grouped_locations,
                                                    altered_activities)
        print('Creating fossil-fuel free carbon anodes for aluminium electrolsysis.')
        altered_activities = treat_aluminium_production(database, fossil_reduction_factor, altered_activities, biosphere3)
    print("------------------------------------")       
    print("Other processes defossilized!")
    print("------------------------------------")  
    
    return altered_activities #altered_activities

def treat_fossil_consumers(database, biosphere3, fossil_reduction_factor, synfuel_split_dict, electricity_locations, emission_factors_dict,
                           synfuel_dict, fossil_identifiers, not_electrifiable_fuels, electrifiable_processes,not_electrifiable_processes,
                           fossil_refinery_processes, grouped_locations, altered_activities):
    #looking for all activities that produce a fossil material
    fossil_acts = [act for act in database if any([identifier==act['reference product'] for identifier in fossil_identifiers])
                              and ('market for' in act['name']
                              or  'market group for' in act['name'])
                              and not 'generic' in act['name']]
    
    if len(fossil_acts)==0:
        raise Exception('Empty list',fossil_acts)
    
    synfuel_subdb = [act for act in database if act['name'] in list(set(flatten(list(synfuel_dict.values()))))]
    
    for fossil_act in fossil_acts:            
        #looking into the consumption of each fossil material and defossilize consumer
        progress_bar(fossil_acts.index(fossil_act)+1, len(fossil_acts), fossil_act['name'])
        altered_activities=defossilize_consumption(database,
                                                   fossil_act,
                                                   biosphere3,
                                                   fossil_reduction_factor,
                                                   synfuel_split_dict,
                                                   synfuel_subdb,
                                                   electricity_locations,
                                                   emission_factors_dict,
                                                   synfuel_dict,
                                                   fossil_identifiers,
                                                   not_electrifiable_fuels,
                                                   electrifiable_processes,
                                                   not_electrifiable_processes,
                                                   fossil_refinery_processes,
                                                   grouped_locations,
                                                   altered_activities)
    return altered_activities

        
def defossilize_consumption(database, fossil_act, biosphere3, fossil_reduction_factor, synfuel_split_dict, synfuel_subdb, electricity_locations, emission_factors_dict,
                            synfuel_dict, fossil_identifiers,not_electrifiable_fuels,electrifiable_processes, not_electrifiable_processes,
                            fossil_refinery_processes, grouped_locations, altered_activities):
    """
    Defossilizes all exchanges between a fossil fuel and consumers.
    
    Args:
                database:                database to treat
                fossil_act:              fossil fuel activity, e.g. market for hard coal
                biosphere3:              biosphere3 database
                fossil_reduction_factor: complete phase-out, 1 unaltered
                synfuel_split_dict:      split between bio and synthetic fuels
                synfuel_subdb:           sub-database with only synfuels and biofuels
                altered_activities:      dictionary of altered activities (for documentation)
    Returns:
                altered_activities:      updated dictionary of altered activities
    
    """
    #get all consumptions that are not zero and are not fossil anyway (e.g., ICE car transport, electricity prod., oil etc).
    consumptions = [exc for exc in fossil_act.upstream() if exc.amount!=0
                                   and not (exc.output['treated'] if 'treated' in exc.output.as_dict().keys() else False)
                                   and not (any([identifier in exc.output['name'] for identifier in fossil_refinery_processes])
                                   or any([identifier==exc.output['reference product'] for identifier in fossil_identifiers]))]
    for consumption in consumptions:
            altered_activities = defossilize_consumer(database,
                                                      consumption,
                                                      biosphere3,
                                                      fossil_reduction_factor,
                                                      synfuel_split_dict,
                                                      synfuel_subdb,
                                                      electricity_locations,
                                                      emission_factors_dict,
                                                      synfuel_dict,
                                                      fossil_identifiers,
                                                      not_electrifiable_fuels,
                                                      electrifiable_processes,
                                                      not_electrifiable_processes,
                                                      fossil_refinery_processes,
                                                      grouped_locations,
                                                      altered_activities)
    return altered_activities
                           
def defossilize_consumer(database, consumption, biosphere3, fossil_reduction_factor, synfuel_split_dict, synfuel_subdb,electricity_locations, emission_factors_dict,
                         synfuel_dict, fossil_identifiers, not_electrifiable_fuels, electrifiable_processes, not_electrifiable_processes,
                         fossil_refinery_processes, grouped_locations, altered_activities):
    """
    Defossilizes one exchange between a fossil fuel and consumers.
    
    Args:
                database:                database to treat
                consumption:             fossil fuel exchange, e.g. market for hard coal to cobalt production
                biosphere3:              biosphere3 database
                fossil_reduction_factor: complete phase-out, 1 unaltered
                synfuel_split_dict:      split between bio and synthetic fuels
                synfuel_subdb:           sub-database with only synfuels and biofuels
                altered_activities:      dictionary of altered activities (for documentation)
    Returns:
                altered_activities:         updated dictionary of altered activities
    
    """
    
    consumer = consumption.output
    fuel     = consumption.input
    amount   = consumption.amount
    conversion_factor =1.0
    loc      = consumer['location']
    
    if loc not in electricity_locations:
        if loc=='NORDEL':
            loc='RER'
        else:
            loc='GLO'
            
        
    #electricify via other process
    if any([consumer['name'] in name for name in list(electrifiable_processes.keys())]):
        water_pump_locs = ['CN', 'DE', 'CA-QC', 'CH', 'US', 'CO', 'ES', 'IN', 'RoW',
                           'FR', 'BR', 'MY', 'ZA', 'MA', 'PE', 'TN', 'PH']
        
        substitute_rp   = electrifiable_processes[consumer['name']]
        if ('water pump operation, diesel' not in consumer['name'] and loc not in water_pump_locs):
            substitute_name = 'market for '+substitute_rp   
        elif (substitute_rp=='water pump operation, electric' and loc=='GLO'):
            substitute_name = 'market for '+substitute_rp
        else:
            substitute_name = substitute_rp
        
        make_non_fossil=False
        mode='customized substitution'
        if 'electricity' in substitute_rp:
            mode='electrification'
            if fuel['unit'] in ['kilogram', 'cubic meter']:
                LHV = list(fuel.production())[0]['properties']['heating value, net']['amount'] #lower heating value
            elif fuel['unit']=='megajoule':
                LHV = 1 # 1MJ
            else:
                LHV = input('{}, lower heating value [MJ/unit]:'.format(fuel))
            conversion_factor = LHV/(3.6*0.9) #[kWh/MJ
            if loc=='RoW':
                loc='GLO'
            if 'CN-' in loc:
                loc='CN'
            if loc in grouped_locations:
                substitute_name = substitute_name.replace('market', 'market group')
        elif 'water pump' in substitute_rp and loc not in water_pump_locs:
            mode='customized substitution'
            loc='GLO'
            
        if 'fossil-waste-treated' not in consumer.as_dict().keys():
            altered_activities = scale_down_fossil_waste_products(consumer, fossil_reduction_factor, altered_activities)
            consumer['fossil-waste-treated']=True
            
        substitutes      =[act for act in database if act['name']==substitute_name
                                                 and act['reference product']==substitute_rp
                                                 and act['location']==loc]
        if substitutes==[]:
            raise Exception('Found no substitute for:', substitute_name, substitute_rp, loc)
            
        conversion_factors = [conversion_factor/len(substitutes)]*len(substitutes)
    
    #electricify via market electricity   
    elif is_electrifiable(consumer, fuel['name'], not_electrifiable_fuels, not_electrifiable_processes, fossil_refinery_processes):
        mode='electrification'
        substitute_rp    = 'electricity, medium voltage'
        substitute_name  = 'market for '+substitute_rp
        
        make_non_fossil=False
        
        if 'electricity' in substitute_rp:
            if fuel['unit'] in ['kilogram', 'cubic meter']:
                LHV = list(fuel.production())[0]['properties']['heating value, net']['amount'] #lower heating value
            elif fuel['unit']=='megajoule':
                LHV = 1 # 1MJ
            else:
                LHV = input('{}, lower heating value [MJ/unit]:'.format(fuel))
            conversion_factor = LHV/(3.6*0.9) #[kWh/MJ
        if loc=='RoW':
            loc='GLO'
        if loc in ['RER w/o CH+DE']:
            loc = 'RER'
        if 'CN-' in loc:
            loc='CN'
        if loc in grouped_locations:
            substitute_name = substitute_name.replace('market', 'market group')
        
        if 'fossil-waste-treated' not in consumer.as_dict().keys():
            altered_activities = scale_down_fossil_waste_products(consumer, fossil_reduction_factor, altered_activities)
            consumer['fossil-waste-treated']=True
        
        substitutes      =[act for act in database if act['name']==substitute_name
                                                 and act['reference product']==substitute_rp
                                                 and act['location']==loc]
        
        if substitutes==[]:
            raise Exception('Found no substitute for:', substitute_name, substitute_rp, loc)
            
        conversion_factors = [conversion_factor/len(substitutes)]*len(substitutes)
    else:
        mode='fuel substitution'
        fuel_rp = fuel['reference product']
        if 'natural gas' not in fuel_rp:
            substitute_name = synfuel_dict[fuel_rp.split(',')[0]]
        else:
            substitute_name = synfuel_dict[fuel_rp]
        
        make_non_fossil=True
        
        substitutes      =[act for act in synfuel_subdb if act['name'] in substitute_name
                                                 and (act['location']==loc
                                                      or act['location']=='GLO'
                                                      or act['location']=='RoW'
                                                      or act['location']=='RER')]
        conversion_factors,a,b = get_fuel_replacement_split(substitutes, synfuel_split_dict)
    
    if substitutes==[]:
        raise Exception('No substitute for {}: {}. Location: {}'.format(substitute_name, substitutes, consumer['location']))
        
    if 'biosphere-defossilized' not in consumer.as_dict().keys():
        if mode == 'fuel substitution':
            mod_fossil_reduction_factor_dict = get_modified_fossil_reduction_factor(consumer, fossil_reduction_factor,
                                                                                    fossil_identifiers, synfuel_dict,
                                                                                    not_electrifiable_fuels,
                                                                                    emission_factors_dict, synfuel_split_dict)
            
            altered_activities = defossilize_biosphere_flows(altered_activities, consumer, biosphere3,
                                                             fossil_reduction_factor, make_non_fossil,
                                                             mod_fossil_reduction_factor_dict)
            consumer['biosphere-defossilized']=True
            consumer.save()

    for new_input, c_f in zip(substitutes, conversion_factors):
        if mode=='fuel substitution':
            add_technosphere_flows_to_activity(consumer, [new_input], [amount*c_f*(1-fossil_reduction_factor)])
            if 'treated' not in consumption.as_dict().keys():
                consumption['amount']*=fossil_reduction_factor
                consumption['treated']=True 
            consumption.save()
        else:
            substitute_input_of_consumers(consumption, new_input, c_f, fossil_reduction_factor)
    
    adjust_uncertainty(consumption)
    consumption.save()
    consumer.save()
    
    altered_activities = track_changes(consumer, altered_activities, mode)

    return altered_activities

def substitute_input_of_consumers(consumption, new_input, conversion_factor, fossil_reduction_factor):
    """
    Scales down exchange and adds new input.
    
    Args:
            consumption:             fossil fuel exchange, e.g. market for hard coal to cobalt production
            new_input:               new input to be added, e.g. charcoal
            conversion_factor:       amount of new input per amount of old input
            fossil_reduction_factor: complete phase-out, 1 unaltered
            
    Returns:
            None
    """
    if new_input!=[] or type(new_input)!=None:
        ex_amount =consumption['amount']
        consumption['amount']*=fossil_reduction_factor
        consumption.save()

        consumer = consumption.output
        #consumer['treated']=True 
        new_amount = ex_amount*(1-fossil_reduction_factor)*conversion_factor
        add_technosphere_flows_to_activity(consumer, [new_input], [new_amount])
    else:
        raise Exception("Something wrong with new_input: ", new_input, consumption.output) 

def progress_bar(current, total, fuel_market, bar_length=50):
    """
    A progress bar to monitor progress.
    
    """
    
    fraction = current / total
    
    arrow = int(fraction * bar_length - 1) * '-' + '>'
    padding = int(bar_length - len(arrow)) * ' '

    ending = '\n' if current == total else '\r'

    print(f'Treating consumers: [{arrow}{padding}] {int(fraction*100)}% {"current: "+fuel_market+"                  "}', end=ending)
    return

def is_electrifiable(consumer, fuel_name, not_electrifiable_fuels, not_electrifiable_processes, fossil_refinery_processes):
    """
    Check whether activity can be electrified as an defossilization option:
    
    Args:
            consumer:      activity to be checked
            fuel_name:     name of the fossil fue
            
    Returns:
            True/False
    
    """
    
    if (any([identifier in consumer['name'] for identifier in ['production','construction', 'mine operation']]) 
        and not any([identifier in consumer['name'] for identifier in fossil_refinery_processes]) 
        and not is_chemical(consumer)
        and not 'carb' in consumer['name']
        and not any([string in consumer['name'] for string in not_electrifiable_processes]) 
        and not any([string in fuel_name for string in not_electrifiable_fuels])):
        return True
    else:
        return False
                            
def is_chemical(activity):
    """
    Check whether activity describes a chemical process.
    
    Args:  activity:     activity to be checked
    Returns: True/False
    
    """
    try:
        clas=next(itertools.dropwhile(lambda s: 'ISIC rev.4 ecoinvent' not in s, activity['classifications']))[1]
    except:
        clas='unspecified'
    return (clas=='2011:Manufacture of basic chemicals' or clas=='2013:Manufacture of plastics and synthetic rubber in primary forms')

def scale_down_fossil_waste_products(activity, fossil_reduction_factor, altered_activities):
    """
    Scaling down fossil waste outputs of activity to be consistent with scaled down fossil input.
    
    Args:   
            activity:                 activity to be treated
            fossil_reduction_factor:  scaling factor 
    Returns: None
    
    """
    waste_identifiers = ['waste mineral oil', 'hard coal ash', 'bilge oil', 'coal slurry', 'coal tar', 'coal gas', 'lignite ash']
    exchanges = [exc for exc in activity.technosphere() 
                     if any([identifier==exc.input['reference product'] for identifier in waste_identifiers])
                        and exc.amount!=0]
    
    for exchange in exchanges:
        exchange['amount']*=fossil_reduction_factor
        exchange.save()

    altered_activities = track_changes(activity, altered_activities, 'scaling waste')
    return altered_activities

def treat_aluminium_production(database, fossil_reduction_factor, altered_activities, biosphere3):
    """
    Replaces consumed carbon anode in aluminium proudction with carbon anode made from charcoal tar and biocoke. 
    Defossilizes biosphere flows of aluminium proudction.
    
    Args:   
            database                   database to be manipulated
            fossil_reduction_factor    0: full defossilization; 1: no change
            altered_activities         list of altered activities
            biosphere3                 biosphere3 database
            
    Returns:
            altered_activities         updated list of altered_activities
    """
    #create bio carbon anode production
    anode_productions = [act for act in database if 'anode production' in act['name'] and 'aluminium electrolysis' in act['name'] and not 'biocoke' in act['name']]
    all_names = [act['name'] for act in database]
    biocoke     = [act for act in database if act['name']=='market for biocoke'][0]
    charcoaltar = [act for act in database if act['name']=='market for charcoal tar'][0]
    for anode_production in anode_productions:
        if anode_production['name']+ ', from charcoal tar and biocoke' not in all_names:
            bio_anode_production = anode_production.copy()

            bio_anode_production['name']+= ', from charcoal tar and biocoke'
            bio_anode_production['code'] = uuid.uuid4().hex

            for exc in bio_anode_production.technosphere():
                if exc.input['reference product'] =='petroleum coke' or exc.input['reference product'] =='coke':
                    exc['input'] = biocoke
                    exc.save()
                elif exc.input['reference product'] =='coal tar' or exc.input['reference product'] =='pitch':
                    exc['input'] = charcoaltar
                    exc.save()

            bio_anode_production.save()
            altered_activities = track_changes(bio_anode_production, altered_activities, 'activity creation')
        
    #change anode input in alumnium production to bio anode
    anode_productions = [act for act in database if 'anode production' in act['name'] and 'biocoke' in act['name']]
    aluminium_productions = [act for act in database if 'aluminium production, primary, liquid' in act['name']]
    for aluminium_production in aluminium_productions:
        for exchange in [exc for exc in aluminium_production.technosphere() if 'anode' in exc.input['name']
                                                    and not 'from charcoal tar and biocoke' in exc.input['name']]:
            paste_or_prebake = exchange.input['name'].split(',')[1].strip()
            new_input = [act for act in anode_productions if paste_or_prebake in act['name']
                                    and act['location']==aluminium_production['location']][0]
            #add bio-based carbon anode
            new_exc = aluminium_production.new_exchange(input =new_input,
                                                     name  =new_input['name'],
                                                     amount=exchange['amount']*(1-fossil_reduction_factor),
                                                     unit= new_input["unit"],
                                                     location= new_input["location"],
                                                     type="technosphere")
            new_exc.save()
            #scale down fossil carbon anode
            exchange['amount']*=fossil_reduction_factor
            exchange.save()
        aluminium_production.save()
        altered_activities = track_changes(aluminium_production, altered_activities, 'fuel substitution')
        altered_activities = fossil_to_nonfossil_biosphere_flows(altered_activities, aluminium_production, biosphere3, fossil_reduction_factor)
        altered_activities = track_changes(aluminium_production, altered_activities, 'defossilize biosphere')
        
    return altered_activities 