import math
import pandas as pd
import os
from pathlib import Path
from tqdm import tqdm
import json
import bw2data as bd
import numpy as np

def import_emission_factors():
    """
    Loads emission factors of fuels.
    """
    parent_dir = Path.cwd().parent
    emission_data        = pd.read_excel(parent_dir / 'scr' / 'fossilfree_ecoinvent' /'data'/'raw'/ 'emission_factors.xlsx', index_col=0)
    global emission_factors_dict
    emission_factors_dict = emission_data.T.to_dict()
    return emission_factors_dict

def adjust_uncertainty(exchange):
    """
    Aligns loc of exchange with amount of exchange.
    
    Args:
            exchange: Exchange of activity
    """
    if 'uncertainty type' in exchange:
        if exchange['uncertainty type']==2: #if lognormal 
            if exchange['amount']!=0:
                exchange['loc']=math.log(abs(exchange.amount))
        elif exchange['uncertainty type']==3: #if normal
            exchange['scale'] = exchange['scale']*abs(exchange.amount/exchange['loc'])
            exchange['loc']=exchange.amount
        exchange.save() 

def adjust_uncertainties(database):
    """
    Harmonized amounts and loc values of all exchanges in database.
    """
    for act in tqdm(database):
        for exc in act.exchanges():
            adjust_uncertainty(exc)
            exc.save()
    print('Adjusted uncertainties for all activities.')
    
def progress_bar(current, total, location, bar_length=50):
    """
    Adds a progress bar in the console.
    """
    fraction = current / total
    
    arrow = int(fraction * bar_length - 1) * '-' + '>'
    padding = int(bar_length - len(arrow)) * ' '

    ending = '\n' if current == total else '\r'

    print(f'Treating activities: [{arrow}{padding}] {int(fraction*100)}% {"current market: "+location+"           "}', end=ending)
    return

def flatten(lst):
    """
    Flattens a nested list.
    """
    return [item for sublist in lst for item in sublist]
        
    
def fossil_to_nonfossil_biosphere_flows(altered_activities, activity, biosphere3, fossil_reduction_factor):
    """
    Function replaces fossil biosphere flows with non-fossil equivalents in a given activity.
    
    Arguments:  altered_activities:              list of altered activities
                activity:                        activity to be defossilized
                fossil_reduction_factor:         % of defossilization, scalar
                biosphere3:                      biosphere3 Database                      
    
    Returns:    altered_activities:              updated list of altered activities
    
    """
    keywords=["Carbon dioxide, fossil", "Carbon monoxide, fossil", "Methane, fossil"]
    from .checks_and_balances import track_changes
    #find all fossil biosphere emissions
    for bio_exc in [exc for exc in activity.biosphere() 
                    if any([exc.input["name"]==keyword for keyword in keywords])]:
        
        non_fossil_bio_flow_name=bio_exc.input["name"].replace("fossil", "non-fossil") #turn to non-fossil
        
        fossil_amount=bio_exc["amount"]
        bio_exc["amount"]*=fossil_reduction_factor #reduce by factor
        bio_exc.save()
        
        #add non-fossil flow or increase non-fossil
        
        if non_fossil_bio_flow_name in [exc.input["name"] for exc in activity.biosphere() 
                                            if exc.input["categories"]==bio_exc.input["categories"]]: #increase
            non_fossil_exc=[exc for exc in activity.biosphere()
                                if exc.input["name"]==non_fossil_bio_flow_name
                                and bio_exc.input["categories"]==exc.input["categories"]][0]
            
            non_fossil_exc["amount"]+=fossil_amount*(1-fossil_reduction_factor)
            non_fossil_exc.save()
        else:
            try:
                non_fossil_flow=[bio_flow for bio_flow in biosphere3 
                                     if bio_flow["name"]==non_fossil_bio_flow_name
                                     and bio_flow["categories"]==bio_exc.input["categories"]][0]

                activity.new_exchange(input=non_fossil_flow,
                                      flow=non_fossil_flow["code"],
                                      name=non_fossil_flow["name"],
                                      amount=fossil_amount*(1-fossil_reduction_factor),
                                      type="biosphere").save()
            except:
                print(non_fossil_bio_flow_name, bio_exc.input["categories"], " not in biosphere3.")
    altered_activities = track_changes(activity, altered_activities, 'defossilize biosphere')
    return altered_activities


def import_fossil_identifiers():
    #fossil fuels
    DATA_DIR = Path(__file__).resolve().parent / "data"
    global identifiers
    identifiers = []
    with open(DATA_DIR /'raw'/'fossil_identifier.txt', "r") as file:
        for line in file:
            identifiers.append(line.strip())  # Remove newline characters

    return identifiers

def import_input_map():
    DATA_DIR = Path(__file__).resolve().parent / "data"
    with open(DATA_DIR /'raw'/ 'input_mapping.json', 'r') as f:
        input_map = json.load(f)
    return input_map

def import_not_electrifiable_fuels():
    #fossil fuels
    DATA_DIR = Path(__file__).resolve().parent / "data"
    global not_electrifiable_fuels
    not_electrifiable_fuels = []
    with open(DATA_DIR /'raw'/ 'not_electrifiable_fuels.txt', "r") as file:
        for line in file:
            not_electrifiable_fuels.append(line.strip())  # Remove newline characters

    return not_electrifiable_fuels

def import_fossil_refinery_processes():
    #fossil fuel refinery processes and processes that are already isolated.
    DATA_DIR = Path(__file__).resolve().parent / "data"  
    global fossil_refinery_processes
    fossil_refinery_processes = []
    with open(DATA_DIR /'raw'/ 'fossil_refinery_processes.txt', "r") as file:
        for line in file:
            fossil_refinery_processes.append(line.strip())  # Remove newline characters, former identifiers2

    return fossil_refinery_processes

def import_not_electrifiable_processes():
    #processes that use carbon as an input in chemical reaction shall not be electrified
    DATA_DIR = Path(__file__).resolve().parent / "data"
    global not_electrifiable_processes
    not_electrifiable_processes = []
    with open(DATA_DIR /'raw'/ "not_electrifiable_processes.txt", "r") as file:
        for line in file:
            not_electrifiable_processes.append(line.strip())  # Remove newline characters

    return not_electrifiable_processes

def import_group_locations():
    #aggregated locations
    DATA_DIR = Path(__file__).resolve().parent / "data"
    global group_locs
    group_locs = []
    with open(DATA_DIR /'raw'/  "group_locations.txt", "r") as file:
        for line in file:
            group_locs.append(line.strip())  # Remove newline characters
    return group_locs

def import_electrifiable_processes():
    #electrifiable processes
    DATA_DIR = Path(__file__).resolve().parent / "data"
    with open(DATA_DIR /'raw'/ "electrifiable_processes.json", "r") as json_file:
        global electrifiable_processes_dict
        electrifiable_processes_dict = json.load(json_file)

    return electrifiable_processes_dict


def import_synfuel_dict():
    DATA_DIR = Path(__file__).resolve().parent / "data"
    global synfuel_dict
    global inverse_synfuel_dict
    df           = pd.read_excel(DATA_DIR /'raw'/  'synfuel_dict.xlsx', index_col=0)
    synfuel_dict = {k: [item for item in v if item is not np.nan] for k, v in df.to_dict(orient='list').items()}
    inverse_synfuel_dict = { v: k for k, l in synfuel_dict.items() for v in l }
    return synfuel_dict


def replace_fuel(altered_activities, activity, fossil_reduction_factor, synfuel_subdb, synfuel_split_dict, vehicles):
    """
    Function replaces fossil fuel inputs with synfuel inputs in a given activity.
    
    Arguments:  altered_activities:              list of altered activities
                activity:                        activity to be defossilized
                fossil_reduction_factor:         % of defossilization, scalar
                database:                        Database with synfuel production processes                      
    
    Returns:    altered_activities:              updated list of altered activities
    """
    from .checks_and_balances import track_changes
    fuels=list(synfuel_dict.keys())
    all_synfuel_names = [ele.replace('market for ', '') for ele in flatten(list(synfuel_dict.values()))]
    
    for exc in [exc for exc in activity.technosphere() 
                    if any([fuel in exc.input["reference product"] for fuel in fuels])
                       and exc.amount!=0
                       and not any([vehicle in exc.input["reference product"] for vehicle in vehicles])
                       and not any([synfuel in exc.input["reference product"] for synfuel in all_synfuel_names])]:
        
        old_amount=exc["amount"]
        exc["amount"]*=fossil_reduction_factor #scale down fossil fuel
        exc.save()
        
        #find right synfuel
        fossil_fuel   =[fuel for fuel in fuels if fuel in exc.input["reference product"]][0]
        synfuel_names =synfuel_dict[fossil_fuel]
        try:
            synfuels=[[act for act in synfuel_subdb if act["name"]==synfuel_name][0] for synfuel_name in synfuel_names]
        except:
            raise Exception("Could not find synfuel for: ", fossil_fuel, synfuel_names)
        
        try:
            fuel_splits, bio, classifications = get_fuel_replacement_split(synfuels, synfuel_split_dict)
        except:
            fuel_splits=[1/len(synfuel) for synfuel in synfuels] #even split
        [add_technosphere_flows_to_activity(activity, [synfuel], [old_amount*(1-fossil_reduction_factor)*fuel_split]) 
                 for fuel_split, synfuel in zip(fuel_splits, synfuels)]
    altered_activities = track_changes(activity, altered_activities, 'fuel substitution')
    return altered_activities
    
    
def defossilize_biosphere_flows(altered_activities, activity, biosphere3, fossil_reduction_factor, make_non_fossil, mod_fossil_reduction_factor_dict={}):
    """
    Function replaces fossil biosphere flows with non-fossil equivalents in a given activity.
    
    Arguments:  altered_activities:              list of altered activities
                activity:                        activity to be defossilized
                fossil_reduction_factor:         % of defossilization, scalar
                biosphere3:                      biosphere3 Database                      
                make_non_fossil:                 boolean: substitute fossil emissions with not fossil ones.
                
    Returns:    altered_activities:              updated list of altered activities
    """
    from .checks_and_balances import track_changes
    keyword_dict ={"Carbon dioxide, fossil" :'CO2',
                   "Carbon monoxide, fossil":'CO2',#corrected below
                   "Methane, fossil"        :'CH4',
                   "Dinitrogen monoxide"    :'N2O'}
    keywords= list(keyword_dict.keys())
    #calculate stochiometric CO2 emissions from pitch, because pitch is not subsituted [no organic replacement] 
    #https://pubs.acs.org/doi/pdf/10.1021/ef00039a014
    
    if fossil_reduction_factor==1:
        return altered_activities
    
    #find all fossil biosphere emissions
    for bio_exc in [exc for exc in activity.biosphere() 
                    if any([exc.input["name"]==keyword for keyword in keywords])]:

        if mod_fossil_reduction_factor_dict!={}:
            fossil_reduction_factor = mod_fossil_reduction_factor_dict[keyword_dict[bio_exc.input['name']]]
        
        non_fossil_bio_flow_name=bio_exc.input["name"].replace("fossil", "non-fossil") #turn to non-fossil
        
        total_fossil_emission=bio_exc["amount"]
        if bio_exc.input["name"]=="Carbon monoxide, fossil":
            
            fuel_based_CO2_emission = sum([exc.amount*emission_factors_dict[exc.input['reference product']]['CO2']
                                                           for exc in activity.technosphere()
                                                              if exc.input['reference product'] in list(emission_factors_dict.keys())])
            #Average CO/CO2 emission in industrial combustion * CO2 emission (source: https://edepot.wur.nl/457839)
            fuel_based_emission = 0.00114*fuel_based_CO2_emission#<---corrected
        else:
            idx = [[keywords[0]]+keywords[2:len(keywords)]][0].index(bio_exc.input["name"]) #index in emission factor (except CO)
            fuel_based_emission = sum([exc.amount*emission_factors_dict[exc.input['reference product']][['CO2', 'CH4', 'N2O'][idx]]
                                                           for exc in activity.technosphere()
                                                              if exc.input['reference product'] in list(emission_factors_dict.keys())])
        
        bio_exc["amount"]=(total_fossil_emission-fuel_based_emission)+fuel_based_emission*fossil_reduction_factor
        if bio_exc["amount"]<0:
            if fossil_reduction_factor>0: #if value is unreasonbly low even without full defossilisation
                bio_exc["amount"]=fossil_reduction_factor*total_fossil_emission
            else:
                bio_exc["amount"]= 0 #slightly different emission factors, than assumed by ecoinvent, could lead to negative values.
        
        #adjust uncertainty
        adjust_uncertainty(bio_exc)
        bio_exc.save()
        activity.save()    
        
        #add non-fossil flow or increase non-fossil
        if make_non_fossil:
            
            #increase existing flow
            if non_fossil_bio_flow_name in [exc.input["name"] for exc in activity.biosphere() 
                                                if exc.input["categories"]==bio_exc.input["categories"]]:
                
                non_fossil_exc=[exc for exc in activity.biosphere()
                                    if exc.input["name"]==non_fossil_bio_flow_name
                                    and bio_exc.input["categories"]==exc.input["categories"]][0]
                
                if fuel_based_emission<=total_fossil_emission:
                    non_fossil_exc["amount"]+=fuel_based_emission*(1-fossil_reduction_factor)
                else: #fuel_based_emission should not overestimate emission, maximum is then total_fossil_emission
                    non_fossil_exc["amount"]+=total_fossil_emission*(1-fossil_reduction_factor)
                non_fossil_exc.save()
                
            else: #add biosphere flow
                
                try:
                    non_fossil_flow = [flow for flow in biosphere3 if flow["categories"]==bio_exc.input["categories"]
                                                                      and non_fossil_bio_flow_name==flow['name']][0]
                    if fuel_based_emission<=total_fossil_emission:
                        amount=fuel_based_emission*(1-fossil_reduction_factor)
                    else:#fuel_based_emission should not overestimate emission, maximum is then total_fossil_emission
                        amount=total_fossil_emission*(1-fossil_reduction_factor)
                        
                    activity.new_exchange(input=non_fossil_flow,
                                          flow=non_fossil_flow["code"],
                                          name=non_fossil_flow["name"],
                                          amount=amount,
                                          type="biosphere").save()
                except:
                    print(non_fossil_bio_flow_name, bio_exc.input["categories"], " not in biosphere3.")
    altered_activities = track_changes(activity, altered_activities, 'defossilize biosphere')
    activity.save()
    return altered_activities

def output_to_self(activity):
    """
    Makes sure all exchanges of activity link to self.
    """
    for exc in activity.exchanges(): # alter output to self
        exc["output"]=activity
        exc.save()
    activity.save()
    return

def comment_to_dict(comment):
    """
    
    ADD DESCRIPTION
    """
    lst=[tuple([key[0:].replace('. ','')+']'][0].split(':')) for key in comment.split(']') if key!='.']
    units=[subele[2] for subele in [ele[1].split(' ') for ele in lst]]
    dictionary=dict([(ele[0]+' '+units[lst.index(ele)], int(ele[1].replace(units[lst.index(ele)],'').strip())) for ele in lst])
    return dictionary

def add_technosphere_flows_to_activity(to_act, inputs, amounts):
    """
    Adds technosphere exchanges to activity.

    Arguments:  to_act:    activity to add exchanges to
                inputs:    technosphere inputs to add
                amounts:   amounts of inputs
               
    Returns:    -
    
    """
    if len(inputs)!=len(amounts):
        raise Exception("Nr. of inputs and amounts not the same: ", inputs, amounts)
    elif any([math.isnan(amount) for amount in amounts]):
        raise Exception("NaN in amounts.", amounts, inputs, to_act)
        
    if len(inputs)>1 and len(set(inputs))==1: #if all inputs are the same
        inputs  = [inputs[0]]
        amounts = [sum(amounts)]
        
    for inpt, amount in zip(inputs, amounts):
        
        if inpt in [exc.input for exc in to_act.technosphere()]: #if exchange is already present, just add amount
            exchange = [exc for exc in to_act.technosphere() if exc.input==inpt][0]
            exchange['amount']+=amount
            exchange.save()
        else: #else, add exchange
            if amount!=0:
                to_act.new_exchange(input=inpt.key,
                                  name=inpt['name'],
                                  amount=amount,
                                  unit=inpt['unit'],
                                  type='technosphere').save()

def add_biosphere_flows(from_act, to_act):
    """
    Copies biosphere flows from one activity to another.

    Args:
            from_act:    activity from which biosphere exchanges are copied
            to_act:      activity to which biosphere exchanges are added

    Returns: to_act
    
    """
    #print("Add biosphere flows to ", to_act)
    exchanges=from_act.biosphere()
    for exchange in exchanges:
        not_keys=["comment", "Source", "properties", "output"]
        keys=[key for key in list(exchange.keys()) if key not in not_keys]
        new_exc=to_act.new_exchange(output=to_act, input=exchange.input, type="biosphere", amount=exchange.amount)
        for key in keys:
            new_exc[key]=exchange[key]
            new_exc.save()

        to_act.save()
    if len(from_act.biosphere())>0 and len(to_act.biosphere())==0:
        raise Exception("Biosphere flows not added!", from_act, to_act)
    return to_act

def get_fuel_replacement_split(substitutes, synfuel_split_dict):
    """
    DEPRECATED
    Assigns replacement fuel options a share.
    
    Args:
            substitutes:         replacement options
            synfuel_split_dict:  split of synthetic and biofuels
    Returns:
            split:               array of shares for array of replacement options
    
    """
    
    classifications = []
    split           = []
    bio             = 0
    for substitute in substitutes:
        clas = check_bio_or_synfuel(substitute['reference product'],substitute['name'])
        classifications.append(clas)
    for clas in classifications:
        share = synfuel_split_dict[clas]/len([e for e in classifications if e==clas])
        if clas=='biogen':
            bio+=share
        split.append(share)
    split = [share/sum(split) for share in split] #balance
    return split, bio, classifications

def get_modified_fossil_reduction_factor(act, fossil_reduction_factor, identifiers, synfuel_dict, not_electrifiable_fuels, emission_factors_dict, synfuel_split_dict):
    """
    Modifies fossil_reduction_factor accounting for limited fuel substitution options (e.g. only biomethane for natural gas).

    Args: 
            act: activity
    Returns:
            mod_fossil_reduction_factor_dict: dictionary with modified reduction factor for each emission species (e.g. CO2, CH4, N2O)

    """
    tuples = [(exc.input['reference product'], exc.amount) for exc in act.technosphere()
                    if exc.input['reference product'] in identifiers 
                      and exc.input['reference product'] not in not_electrifiable_fuels]
    
    df = pd.DataFrame(tuples, columns=['fuel', 'amount'])
    substitute_list = [synfuel_dict[crop_fuel(fuel)] for fuel in df.fuel]
    df['subst_type']= [get_sub_type([check_bio_or_synfuel(sub, sub) for sub in substitute]) for substitute in substitute_list]
    df['fossil_remaining'] = [0+fossil_reduction_factor 
                                  if typ=='biogen' 
                                  else 1 if typ=='syngen' 
                                  else synfuel_split_dict['syngen']+synfuel_split_dict['biogen']*fossil_reduction_factor 
                                      for typ in df.subst_type]
    mod_fossil_reduction_factor_dict = {}
    for species in [e for e in list(list(emission_factors_dict.values())[0].keys()) if e not in ['remark', 'per unit']]:
        df['kg_{}'.format(species)]    = [amount*emission_factors_dict[fuel][species] for fuel, amount in zip(df.fuel, df.amount)]
        
        if sum(df['kg_{}'.format(species)])==0: #in case that fuel has no emissions (e.g. natural gas, burned in gas motor, for storage)
            mod_fossil_reduction_factor = 1.0
        else:
            mod_fossil_reduction_factor = sum([f*emission/sum(df['kg_{}'.format(species)]) 
                                                   for f, emission in zip(df.fossil_remaining, df['kg_{}'.format(species)])])
        mod_fossil_reduction_factor_dict[species] = mod_fossil_reduction_factor
    return mod_fossil_reduction_factor_dict

def get_sub_type(subs):
    """
    Checks if fuel substitutes (subs) are either only synthetic, biogenic, or both.
    """
    if len(list(set(subs)))==1:
        return list(set(subs))[0]
    else:
        return 'both'

def crop_fuel(fuel):
    """
    Crops fuel string.
    """
    if 'pressure' in fuel:
        return fuel.replace(', vehicle grade','')
    else:
        return fuel.replace(', low-sulfur','').replace(', unleaded','').replace(', two-stroke blend','').replace(', diesel','')

def check_bio_or_synfuel(rp, name):
    """
    Check if product is a synfuel or a biofuel.
    Args:
            rp:    reference product
            name:  activity name
    Returns:
            clas:  synfuel or biofuel as string
    """
    if 'synthetic' in rp or 'electrolysis' in name or 'synthetic' in name or 'electric' in name:
        clas = 'syngen'
    elif 'bio' in rp or 'char' in rp or 'fermentation' in rp:
        clas = 'biogen' 
    else:
        clas = input(rp+': syngen or biogen?')
        if clas not in ['syngen', 'biogen']:
            clas = input('Either syngen or biogen!')
    return clas

def indices(iterable, obj, compare):
    """
    Returns indices in array that satisfies the condition iterable[index] >/</== obj.
    """
    try:
        if compare=='>':
            return [index for index, elem in enumerate(iterable) if elem > obj]
        elif compare=='<':
            return [index for index, elem in enumerate(iterable) if elem < obj]
        elif compare=='==':
            return [index for index, elem in enumerate(iterable) if elem == obj]
    except:
        print([(elem, type(elem)) for elem in iterable])
        raise Exception("String instead of float")
        
def correct_fossil_emissions_of_synfuels(db, bio):
    synfuel_market_names = [fuel for fuel in list(inverse_synfuel_dict.keys()) if 'synthetic' in fuel]
    markets = [act for act in db if act['name'] in synfuel_market_names]
    fuels   = [act['reference product'] for act in markets]
    consumers = list(set(flatten([[consumption.output for consumption in list(market.upstream())] for market in markets])))
    [correct_fossil_emission(consumer, fuels, bio) for consumer in tqdm(consumers)]

def correct_fossil_emission(consumer, fuels, bio):
    inpts, amounts =  zip(*[(exc.input['name'], exc.amount) 
                                for exc in consumer.technosphere() if exc.input['reference product'] in fuels])
    CO2_fossil = sum([emission_factors_dict[inverse_synfuel_dict[inpt]][0]*amount*correction_dict[inpt]
                          for inpt, amount in zip(inpts, amounts) if inpt in inpt in inverse_synfuel_dict.keys()])
    CH4_fossil = sum([emission_factors_dict[inverse_synfuel_dict[inpt]][1]*amount*correction_dict[inpt]
                          for inpt, amount in zip(inpts, amounts) if inpt in inpt in inverse_synfuel_dict.keys()])
    CO2_excs = [exc for exc in consumer.biosphere() if exc.input['name']=='Carbon dioxide, non-fossil']
    CH4_excs = [exc for exc in consumer.biosphere() if exc.input['name']=='Methane, non-fossil']
    
    #print('Found {} exchanges to correct'.format(len(CO2_excs+CH4_excs)))
    if len(CO2_excs)>0:
        for exc in CO2_excs:
            fossi_eq_bioflow = [flow for flow in bio 
                                    if flow['name']=='Carbon dioxide, fossil' and flow['categories']==exc.input['categories']][0]
            new_amount    = exc.amount - CO2_fossil/len(CO2_excs)
            if new_amount>0:
                exc['amount'] = new_amount
            else:
                exc['amount'] = 0
            add_fossil_carbon(consumer, exc, fossi_eq_bioflow, CO2_fossil/len(CO2_excs))
            exc.save()
            consumer.save()
    if len(CH4_excs)>0:
        for exc in CH4_excs:
            fossi_eq_bioflow = [flow for flow in bio 
                                    if flow['name']=='Methane, fossil' and flow['categories']==exc.input['categories']][0]
            new_amount    = exc.amount - CH4_fossil/len(CH4_excs)
            if new_amount>0:
                exc['amount'] = new_amount
            else:
                exc['amount'] = 0
            add_fossil_carbon(consumer, exc, fossi_eq_bioflow, CH4_fossil/len(CH4_excs))
            exc.save()
            consumer.save()
            
def add_fossil_carbon(to_act, old_exc, new_flow, new_amount):
    """
    Adds a new biosphere exchange to an activity.

    Args:
            to_act:     activity to which the biosphere exchange is added
            old_exc:    Another biopshere exchange as template
            new_flow:   New biopshere flow to be added
            new_amount: New amount
    """
    not_keys=["comment", "Source", "properties", "output", 'input', 'type', 'amount', 'loc']
    keys=[key for key in list(old_exc.keys()) if key not in not_keys]

    new_exc=to_act.new_exchange(output=to_act, input=(new_flow['database'],new_flow['code']),
                                type="biosphere", amount=new_amount)
    new_exc.save()
    if 'uncertainty type' in old_exc.as_dict().keys():
        if old_exc['uncertainty type']==2:
            new_exc['loc']=np.log(new_amount)
        elif old_exc['uncertainty type']==1:
            new_exc['loc']=new_amount
    for key in keys:
        new_exc[key]=old_exc[key]
    new_exc.save()
    to_act.save()

def get_search_tuple(act, keys, location):
        locs_with_market_group = ['BR', 'CA', 'CN', 'Canada without Quebec', 'ENTSO-E',
                                  'Europe without Switzerland', 'GLO', 'IN', 'RAF', 'RAS',
                                  'RER', 'RLA', 'RME', 'RNA', 'UCTE', 'US']
        if location in locs_with_market_group:
            return tuple([act[key] for key in keys])
        else:
            return tuple([act[key].replace(' group', '') for key in keys])

def copy_to_new_location(act, location):
    """
    Copying activity (act) to new location.
    Returns: new-act: activity at new location
    """
    new_act = act.copy()
    new_act['location']= location
    new_act['key']= (act['database'])
    new_act.save()
    return new_act
    
def get_variants_as_dict(db_dict, search):
        variant_dict = [dct for dct in db_dict if (dct['name'], dct['product'], dct['unit'])==search]
        return variant_dict

def get_regional_variant(db_dict, search, location, priorities, db, base_act):
    """
    Searches for regional variant of activities.

    Args:
        db_dict: fast access representation of database
        search: filter tuple with name, reference product
        location: the location which is being treated
        priorities: second best locations if local match fails
        db: database
        base_act: activity, for which local variant is seeked
    Returns:
        variant: regional variant (activity)
    """

    variants = get_variants_as_dict(db_dict, search)

    for variant in variants:
        if location==variant['location']:
            return db.get(variant['code'])
    variant = []
    idx     = 0
    while not variant:
        try:
            priority = priorities(idx)
        except:
            return base_act
        variant = [db.get(variant['code']) for variant in variants if variant['location']==priority][0]
    return variant

def switch_to_regional_inputs(act, db, db_dict, location, priorities):
    """
    Regionalizes technosphere exchanges of activity if possible.
    
    Args:
        act: activity to be regionalized
        db: database
        db_dict: fast access representation of db
        location: location for regionalization
        priorities: second best locations if local match fails
    Returns:
        act: regionalized activity
    """
    for exc in act.technosphere():
        inpt = exc.input
        search = get_search_tuple(inpt, ['name', 'reference product', 'unit'], location)
        variant= get_regional_variant(db_dict, search, location, priorities, db, inpt)
        if variant!=inpt:
            act    = swap_exchange(db, act, inpt.key, variant.key)
    return act

def swap_exchange(db, act, old_input_key, new_input_key):
    """
    Swaps one exchange for another in activity.
    
    Args:
        db: database
        act: activity with exchanges
        old_input_key: key of input to be removed
        new_input_key: key of new input to be added
    Returns:
        act: activity treated
    """
    excs               = [exc for exc in act.technosphere() if exc.input == old_input_key]
    inpt = db.get(new_input_key[1])
    for exc in excs:
        exc['input']             = new_input_key
        exc['reference product'] = inpt['reference product']
        exc['name']              = inpt['name']
        exc.save()
    act.save()
    return act

def regionalise_activity(act, location, db, db_dict, priorities):
    """
    Regionalizes activity and technosphere inputs.
    Args:
        act: Activity to be regionalized
        location: new location
        db: database
        db_dict: fast access representation of db
        priorities: second best locations if local match fails
    Returns:
        new_act: regionalized activity

    """
    new_act= copy_to_new_location(act, location)
    new_act= switch_to_regional_inputs(new_act, db, db_dict, location, priorities)
    db_dict.append({'name': new_act['name'],
                     'product': new_act['reference product'],
                     'unit': new_act['unit'],
                     'code': new_act['code'],
                     'location': new_act['location']})

    return new_act, db_dict

def get_voltage_level(rp):
    return rp.split(' voltage')[0].split(', ')[1]

def change_geographies(imp_data = None, from_location='RER', to_location='GLO', database_only=True, cc_name='carculator db', database=None):
    electricity_markets = [act for act in database 
                           if ('market for electricity' in act['name']
                           or 'market group for electricity' in act['name'])
                           and 'industry' not in act['name']
                           and 'internal' not in act['name']
                           and act['location']==to_location]
    if len(electricity_markets)==0:
        raise Exception('No electricity markets found for this location:', to_location)
    
    if len(imp_data)==0:
        raise Exception('imp_data empty:', imp_data)
    
    new_imp_data = [change_geography(dataset,
                               from_location=from_location,
                               to_location=to_location, 
                               database_only=database_only, 
                               cc_name=cc_name,
                               new_db_name = database.name,
                               electricity_markets=electricity_markets) for dataset in imp_data
                           ]
    return new_imp_data

def change_geography(dataset, from_location='RER', to_location='GLO', database_only=True, cc_name='carculator db', new_db_name= 'ecoinvent-3.8-cutoff_fossilfree', electricity_markets=[]):
    
    if dataset['location']==from_location:
        dataset['location']= to_location
    if 'exchanges' in dataset.keys():
        for i, exc_ds in enumerate(dataset['exchanges']):
            if exc_ds['database']==cc_name:
                change_geography(exc_ds, from_location='RER', to_location='GLO')
            if exc_ds['database'] not in ['biosphere3', cc_name]:
                if 'electricity' in exc_ds['reference product']:
                    change_geography(exc_ds, from_location=exc_ds['location'], to_location='GLO')
            if exc_ds['database']==cc_name and 'kilowatt hour'==exc_ds['unit'] and 'reuse' not in exc_ds['name'] and 'incineration' not in exc_ds['name']:
                voltage_level = get_voltage_level(exc_ds['reference product'])
                try:
                    electricity_market = [act for act in electricity_markets 
                            if act['reference product']=='electricity, {} voltage'.format(voltage_level)][0]
                except:
                    raise Exception(voltage_level, exc_ds['reference product'], exc_ds['name'])
                exc_ds = {
                    'name': electricity_market['name'],
                    'amount': exc_ds['amount'],
                    'database': new_db_name,
                    'location': 'GLO',
                    'unit': 'kilowatt hour',
                    'type': 'technosphere',
                    'reference product': electricity_market['reference product'],
                    'tag': 'electricity',
                    'input': (new_db_name, electricity_market['code'])
                    }
                dataset['exchanges'][i] = exc_ds
                
    return dataset

def migrate_exchanges(data, from_version='3.8', to_version='3.9'):
    biosphere_map_dict    = get_biosphere3_map_dict(from_version, to_version)
    technosphere_map_dict = get_technosphere_map_dict(from_version, to_version)
    new_data = [migrate_flows(ds, biosphere_map_dict, technosphere_map_dict) for ds in data]
    return new_data

def migrate_flows(dataset, biosphere_map_dict, technosphere_map_dict):
    for i, exc in enumerate(dataset['exchanges']):
        if exc['type']=='biosphere' and 'noise' not in exc['name']:
            try:
                if exc['categories']==('water', 'ground-', 'long-term'):
                    exc['categories'] = ('water', 'ground-, long-term')
                match = biosphere_map_dict[(exc['name'], exc['categories'])]
            except:
                raise Exception(exc)
            dataset['exchanges'][i] = {'name':  match['name'],
                                        'amount': exc['amount'],
                                        'database': exc['database'],
                                        'unit': exc['unit'],
                                        'categories': exc['categories'],
                                        'type': exc['type'],
                                        'input': (exc['database'], match['code'])
                                        }
        elif exc['type']=='technosphere' and (exc['name'], exc['reference product'], exc['location']) in technosphere_map_dict.keys():
            try:
                match = technosphere_map_dict[(exc['name'], exc['reference product'], exc['location'])]
            except:
                raise Exception(exc)
            for key in match.keys():
                dataset['exchanges'][i][key] = match[key]
    return dataset

def get_biosphere3_map_dict(from_version='3.8', to_version='3.9'):
    DATA_DIR = Path(__file__).resolve().parent / "data"
    match_df_raw = pd.read_excel(DATA_DIR /'raw'/ 'biosphere_flow_mapping.xlsx', index_col=0)
    match_df_raw['categories'] = [eval(val) for val in match_df_raw['categories']]
    match_df = match_df_raw.set_index(['{}_name'.format(from_version), 'categories'])[['{}_name'.format(to_version), '{}_code'.format(to_version)]].T
    match_df.index = ['name', 'code']

    match_df = match_df.loc[:, ~match_df.columns.duplicated()] #remove duplicated columns

    map_dict = match_df.to_dict()
    return map_dict


def get_technosphere_map_dict(from_version='3.8', to_version='3.9'):
    DATA_DIR = Path(__file__).resolve().parent / "data"
    match_df_raw = pd.read_excel(DATA_DIR /'raw'/ 'technosphere_mapping.xlsx')
    match_df = match_df_raw.set_index(['name_{}'.format(from_version), 'reference product_{}'.format(from_version), 'location_{}'.format(from_version)])[['name_{}'.format(to_version), 'reference product_{}'.format(to_version), 'location_{}'.format(to_version)]].T
    match_df.index = ['name', 'reference product', 'location']
    map_dict = match_df.to_dict()
    return map_dict
