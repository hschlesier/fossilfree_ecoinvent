import bw2calc as bc
import bw2data as bd
import pandas as pd
from datetime import datetime
from pathlib import Path
from openpyxl import load_workbook
import itertools
import numpy as np
from tqdm import tqdm


def balance_captured_carbon(database, biosphere3):
    """
    Closes carbon balance for carbon capture and synthetic fuel production.
    """
    CC = [act for act in database if 'carbon dioxide, captured from atmosphere' in act['name'] or 'production, synthetic' in act['name'].lower() or 'production, from methanol,' in act['name']]
    co2 = biosphere3.get('f9749677-9c9f-4678-ab55-c607dfdc2cb9') #CO2, fossil (air)
    for cc in CC:
        for exc in cc.biosphere():
            if exc.input['name']=='Carbon dioxide, in air':
                exc['name']   = co2['name']
                exc['amount'] *= -1 
                exc['categories'] = co2['categories']
                exc['input'] = co2.key
                exc.save()
            
            if exc.input['name']=='Carbon dioxide, non-fossil':
                exc['name']   = co2['name']
                exc['categories'] = co2['categories']
                exc['input'] = co2.key
                exc.save() 
        cc.save()

def get_classification_dict():
    """
    Loads dictionary of currently unclassified activities and their ISIC classification.
    """
    # Absolute path to the current file
    PACKAGE_DIR = Path(__file__).resolve().parent
    DATA_DIR = PACKAGE_DIR / "data"
    
    filepath =      DATA_DIR /'raw' / 'unclassified_activities.xlsx'
    unclassified_df = pd.read_excel(filepath)
    classification_dict = unclassified_df.set_index(['name', 'product'])[['ISIC rev. 4']].to_dict()
    return classification_dict

def add_other_classifications(db, classification_dict):
    """
    Adds ISIC classification to activities in database according to a dictionary.
    """
    keys = classification_dict['ISIC rev. 4'].keys()
    count=0
    for act in db:
        if (act['name'], act['reference product']) in keys:
            clas = classification_dict['ISIC rev. 4'][(act['name'], act['reference product'])]
            act['classifications'] = [('ISIC rev.4 ecoinvent', clas)]
            act.save()
            count+=1
    print('Added {0} classifications in {1}'.format(count, db.name))        

def add_classification(db):
    """
    General approach to add ISIC classifications to unclassified activities in database.
    """
    electricity_acts_no_clas = [act for act in db if 'classifications' not in act.as_dict().keys() and act['unit']=='kilowatt hour']
    heat_acts_no_clas        = [act for act in db if 'classifications' not in act.as_dict().keys()
                             and 'heat' in act['reference product'] and not 'wheat' in act['name'] and act['unit']=='megajoule']
    trans_pas_acts_no_clas = [act for act in db 
                              if 'classifications' not in act.as_dict().keys() and 'passenger' in act['name']
                             and act['unit'] in ['ton kilometer', 'person kilometer', 'ton-kilometer', 'kilometer']
                             and act['name'] not in ['Catenary system', 'pipeline, supercritical CO2/km']]
    trans_fre_acts_no_clas = [act for act in db 
                              if 'classifications' not in act.as_dict().keys() and 'freight' in act['name']
                             and act['unit'] in ['ton kilometer', 'person kilometer', 'ton-kilometer', 'kilometer']
                             and act['name'] not in ['Catenary system', 'pipeline, supercritical CO2/km']]
    transport_acts_w_clas = [act for act in db if 'transport' in act['reference product']
                              and ('classifications' in act.as_dict().keys() and
                                   act['classifications'][0][1]=='2011:Manufacture of basic chemicals')]

    clas_electricity = [('ISIC rev.4 ecoinvent', '3510:Electric power generation, transmission and distribution')]
    clas_heat        = [('ISIC rev.4 ecoinvent', '3530:Steam and air conditioning supply')]
    clas_transport_w = [('ISIC rev.4 ecoinvent', '4922:Other passenger land transport')]
    clas_trans_fre   = [('ISIC rev.4 ecoinvent', '4923:Freight transport by road')]
    clas_trans_pas   = [('ISIC rev.4 ecoinvent', '4922:Other passenger land transport')]

    act_list = [electricity_acts_no_clas, heat_acts_no_clas, trans_pas_acts_no_clas, trans_fre_acts_no_clas, transport_acts_w_clas]
    classifications = [clas_electricity, clas_heat, clas_trans_pas, clas_trans_fre, clas_transport_w]

    for acts, classification in zip(act_list, classifications):
        for act in acts:
            act['classifications'] = classification
            act.save()        

def check_production_amount(database):
    """
    Checks if all activities in database have a production amount assigned. If not assigns 1.0. 
    """
    altered_acts=[]
    for act in database:
        try:
            act["production amount"]
        except:
            act["production amount"]=1.0
            act.save()
            altered_acts.append(act)
    print("Added production amount for {} activities.".format(len(altered_acts)))

def replace_database_name(s, old_db_names, new_db_name):
    for old_db_name in old_db_names:
        if s==old_db_name:
            s = new_db_name
    return s

def add_ISIC_classifications(database):
    """
    Adds ISIC classifications to newly created activities in database. 
    """
    print('Adding classifications to database...')
    add_classification(database) #general approach
    classification_dict = get_classification_dict()
    add_other_classifications(database, classification_dict) #detailed approach for rest
    print('Finished classifications')
    
def check_production(database):
    """
    Checks if all activities in database have a production exchanges and adds it if necessary.
    """
    print('Checking production...')
    added=0
    for act in tqdm(database):
        try:
            list(act.production())[0].input
        except:
            production=act.new_exchange(output=(act['database'], act['code']), input=(act['database'],act['code']),
                                type="production", amount=1.0)
            production.save()
            act.save()
            added+=1
    print('Finished check. Added {} productions'.format(added))    
        
def relink_exchanges_to_self(database, old_db_name, new_db_name):
    """
    For all activities in the database the technosphere inputs are relinked from one database to another.

    Args:
            database:    database with activities to be relinked.
            old_db_name: database name for which edges are cut.
            new_db_name: database name for which the cut edges should be linked to.
    """
    codes_or = set([act['code'] for act in bd.Database(old_db_name[0])])
    codes_ff = set([act['code'] for act in bd.Database(new_db_name)])
    codes    = list(codes_ff.difference(codes_or))
    
    for code in tqdm(codes):
        act = database.get(code)
        for exc in list(act.technosphere())+list(act.production()):
            relink_input_output(exc, old_db_name, new_db_name)
        act.save()
    print('Checked whether all exchanges link to self.')
    
def relink_input_output(dataset, old_db_name, new_db_name):
    """
    Relinks edge (exchange) from on database to another.

    Args:
            dataset:     edges dataset
            old_db_name: database name for which edges are cut.
            new_db_name: database name for which the cut edges should be linked to.
    """
    try:
        dataset['database'] = new_db_name
        dataset['input'] = (replace_database_name(dataset['input'][0], old_db_name, new_db_name), dataset['input'][1])
        dataset['output']= (replace_database_name(dataset['input'][0], old_db_name, new_db_name), dataset['output'][1])
        dataset.save()
    except:
        print(dataset)
        raise Exception(dataset.as_dict())

def get_change_report(database, altered_activities):
    """
    Creates a report of altered activities in the database.    
    Args:
            database:           The database to be checked.
            altered_activities: Dictionary with altered activities.
    Returns:
            DataFrame with altered activities and their details.
    """
    if altered_activities=={}:
        print('No activities were altered. Return empty report.')
        return pd.DataFrame()
    else:
        change_report = pd.DataFrame(altered_activities).T
        for var in ['reference product', 'location', 'unit']:
            change_report[var] = [database.get(code)[var] for code in change_report.index]
        change_report = change_report[['name','reference product', 'location', 'unit','mode']]
        change_report['mode'] = [list(set(mode)) for mode in change_report['mode']]
        return change_report
    
def track_changes(activity, altered_activities, mode):
    """
    Tracks changes in activities and adds them to the altered_activities dictionary.

    Args:
            activity:          activity that was altered.
            altered_activities: dictionary with altered activities.
            mode:              mode of change (e.g. 'added', 'modified', 'deleted').
    """
    if activity['code'] not in altered_activities.keys():
        altered_activities[activity['code']] = {'name': activity['name'], 'mode': [mode]}
    else:
        altered_activities[activity['code']]['mode'].append(mode)
    return altered_activities

def checks_and_balances(db, biosphere3, base_db_name):
    """ Performs various checks and balances on the database.  
    Args:
        db:           The database to be checked and balanced.
        biosphere3:   The biosphere database to be used for carbon balance.
        base_db_name: The name of the base database from which exchanges should be relinked.
    """
    from .utils import adjust_uncertainties
    
    #Checks exchanges
    relink_exchanges_to_self(database   = db,
                         old_db_name = [base_db_name, 'lci-synfuels'],
                         new_db_name = db.name
                        )
    #Check if all production amounts are defined
    check_production_amount(database = db)
    
    #Add ISIC classifications
    add_ISIC_classifications(database = db)
    
    #Checks productions
    check_production(database = db)

    #harmonize uncertainty
    adjust_uncertainties(database = db)
    
    #Closes carbon balance for carbon capture and utilization
    balance_captured_carbon(database = db, biosphere3=biosphere3)
    
    #Remove zero amount exchanges
    clean_database_from_zero_amount_flows(database=db)

def clean_database_from_zero_amount_flows(database):
    """
    Removes of all zero edges (exchanges) in the database.
    """
    print("Clean database from zero amount flows.")
    count=0
    for act in tqdm(database):
        count+=1
        for exc in act.exchanges():
            if exc.amount == 0:
                exc.delete()
    
def progress_bar(current, total, db_name , bar_length=50):
    """ Displays a progress bar in the console. 

    Args:
        current:     Current progress value.
        total:       Total value to reach.
        db_name:     Name of the database for which the progress is displayed.
        bar_length:  Length of the progress bar in characters.
    """
    fraction = current / total

    arrow = int(fraction * bar_length - 1) * '-' + '>'
    padding = int(bar_length - len(arrow)) * ' '

    ending = '\n' if current == total else '\r'

    print(f'Adding activities: [{arrow}{padding}] {int(fraction*100)}% {db_name}', end=ending)
    return

