#import packages
import pandas as pd
from checks_and_balances import track_changes
import numpy as np
from tqdm import tqdm
import uuid
from pathlib import Path
import json
from utils import add_biosphere_flows, flatten, indices, fossil_to_nonfossil_biosphere_flows, import_emission_factors, regionalise_activity, import_input_map

def import_heat_classes():
    parent_dir = Path.cwd().parent
    # Import the dictionary from the JSON file
    with open(parent_dir / "data/raw/heat_classes.json", "r") as json_file:
        global heat_dict
        heat_dict = json.load(json_file)

def import_heat_keywords():
    parent_dir = Path.cwd().parent
    # Import the dictionary from the JSON file
    with open(parent_dir / "data/raw/heat_keywords.json", "r") as json_file:
        global keyword_dict
        keyword_dict = json.load(json_file)

def heat_markets_setup(database, database_bio , fossil_reduction_factor, heat_split, electricity_locations, ei_version, input_map, altered_activities):
    """
    This method creates new fossil free market processes for heat production.
    
    Therefore we copy all other fossil market heat processes and substitute fossil processes with fossil free ones
    
    Args:
        database:                 database to be treated
        database_bio:             biosphere3 database
        fossil_reduction_factor:  0 full defossilization, 1 unaltered
    
    Returns:
        altered_activities:      dictionary of altered activities (for documentation)
    """
    parent_dir = Path.cwd().parent
    
    #create markets for biomethane, high pressure based on industrial furnace and biomethane, high pressure
    biomethane_codes=[]
    heat_natural_gas_acts=[act for act in database 
                    if ("heat production, natural gas, at industrial furnace" in act["name"]
                    or "heat and power co-generation, natural gas," in act["name"])
                    and "megajoule"==act["unit"]
                    ]
    #print("Found ", len(heat_natural_gas_acts), "heat producing activities based on natural gas.")
    all_names = [act['name'] for act in database]
    for act in heat_natural_gas_acts:
    
        market_code   =uuid.uuid4().hex
        market_name   =act["name"].replace("natural gas", "biomethane")
        market_product=act["reference product"].replace("natural gas", "biomethane")
        
        #only if biomethane market is not present in that location
        if market_name not in all_names:
            biomethane_codes.append(market_code)
            
            try:
                heat_market = database.new_activity(code=market_code,
                                                    name=market_name,
                                                    unit=act["unit"],
                                                    type='process',
                                                    location=act["location"],
                                                    comment=get_heat_properties_from_activity(act))


                #print("Created ", heat_market)
                heat_market.save()
                heat_market["reference product"]= market_product
                heat_market["production amount"]= 1.0
                heat_market.save()
            except:
                print(market_name, market_code, act["location"])
                raise Exception('Error')

            altered_activities = track_changes(heat_market, altered_activities, 'activity creation')

            for exc in [exc for exc in act.technosphere()]:
                if exc.input["reference product"]!="natural gas, high pressure":
                    exc_input=exc.input
                else: #if there is natural gas, high pressure input --> substitute with biomethane, high pressure, idealy same location
                    for bm_act in [act for act in database if act["name"]=="market for biomethane, high pressure"]:
                        if bm_act["location"]==act["location"]:
                            biomethane_act=bm_act
                            break
                        elif bm_act["location"]=="RoW":
                            biomethane_act=bm_act
                        elif  bm_act["location"]=="GLO":
                            biomethane_act=bm_act

                    exc_input=biomethane_act
                heat_market.new_exchange(input     =exc_input,
                                           name    =exc_input["name"],
                                           amount  =exc.amount,
                                           unit    =exc_input["unit"],
                                           location=exc_input["location"],
                                           type='technosphere').save()
                
            heat_market = add_biosphere_flows(act, heat_market)

            altered_activities = fossil_to_nonfossil_biosphere_flows(altered_activities, heat_market, database_bio, fossil_reduction_factor)

    if biomethane_codes==[]:
        biomethane_codes = [act['code'] for act in database 
                    if ("heat production, biomethane, at industrial furnace" in act["name"]
                    or "heat and power co-generation, biomethane," in act["name"])
                    and "megajoule"==act["unit"]
                    ]
    print("Added biomethane market")
    
    #create new heat process based on electric resistance / eletric arc furnace turning electricity into heat
    resistor_heat_code   =uuid.uuid4().hex
    resistor_heat_name   ="heat production, electric resistance"
    resistor_heat_product="heat, district or industrial, electric resistance"
    
    if resistor_heat_name not in all_names:
        priorities =['RoW', 'RER', 'GLO'] #if no match in location, search in RoW, else RER, else globally
        db_dict = [{'name': act['name'], 'product':act['reference product'],'unit' :act['unit'],
                    'code': act['code'], 'location': act['location']} for act in database]
        try:
            resistor_heat_market = database.new_activity(code=resistor_heat_code,
                                                    name=resistor_heat_name,
                                                    unit="megajoule",
                                                    type='process',
                                                    location="GLO")
            resistor_heat_market.save()
            resistor_heat_market["reference product"]= resistor_heat_product
            resistor_heat_market["production amount"]= 1.0
            resistor_heat_market.save()
        except:
            raise Exception(database)

        #add exchanges
        electric_arc_furnace=database.get(input_map[ei_version]['EAF'])
        electricity         =[act for act in database
                                      if act["name"]=="market group for electricity, high voltage" and act["location"]=="GLO"][0]

        resistor_heat_market.new_exchange(input=electric_arc_furnace,
                                           name=electric_arc_furnace["name"],
                                           amount=7.56E-12,    #1 unit / (500 000 t/a steel for 50a * 1.47 kWh/kg steel *3.6 MJ/kWh) (max of steel, electric in ei3.8
                                           unit="megajoule",
                                           type="technosphere").save()

        resistor_heat_market.new_exchange(input=electricity,
                                           name=electricity["name"],
                                           amount=0.277778,    #1 MJ = 0.277778 kWh
                                           unit=electricity["unit"],
                                           type="technosphere").save()

        altered_activities = track_changes(resistor_heat_market, altered_activities, 'activity creation')

        for location in electricity_locations:
            regional_resistor_act, db_dict = regionalise_activity(resistor_heat_market, location, database, db_dict, priorities)
            altered_activities = track_changes(regional_resistor_act, altered_activities, 'activity creation')
            
    print("Added heat process with electric resistor.") 
   
    #create new global heat markets
    file=pd.ExcelFile(parent_dir / 'data/raw/heat_processes_allocation.xlsx')
    sheets = file.sheet_names #get all sheet names
    for sheet in sheets:
        df = file.parse(sheet)
        if len(df["Fossil-based fuel"])!=0:
            temp_level =sheet[sheet.find('TEMP- ')+len('TEMP- '):sheet.find('|')] #find temperature level
            power_level=str(sheet[len(sheet)-1]) #find power level
            
            if "market for heat, "+heat_dict[temp_level]+", "+heat_dict[power_level] not in [act["name"] for act in database
                                                                                             if "market for heat" in act["name"]]:
                market_name="market for heat, "+heat_dict[temp_level]+", "+heat_dict[power_level]
                market_code=uuid.uuid4().hex
                market_product="heat, "+heat_dict[temp_level]+", "+heat_dict[power_level]
                print('Creating market for heat, {}, {}'.format(heat_dict[temp_level], heat_dict[power_level]))

                glo_heat_market = database.new_activity(code=market_code,
                                                    name=market_name,
                                                    unit="megajoule",
                                                    type='process',
                                                    location="GLO")
                glo_heat_market["reference product"]= market_product
                glo_heat_market["production amount"]= 1.0
                glo_heat_market.save()

                renew_act_data  = file.parse(sheet)[['ff_KEY_{}'.format(ei_version), 'Biofuel/biomass']].dropna(subset=['ff_KEY_{}'.format(ei_version)])
                renew_act_keys  = [(database.name, eval(key)[1]) for key in renew_act_data['ff_KEY_{}'.format(ei_version)].to_list()]
                renew_names = [database.get(key[1])['name'] for key in renew_act_keys]
                renew_fuels = renew_act_data['Biofuel/biomass'].fillna('none')
                renew_heat_processes = [database.get(key[1]) for key in renew_act_keys]

                amounts=get_split_of_heat_processes(renew_names, heat_split, renew_fuels)

                #fill with suitable renewable processes
                glo_heat_market=[act for act in database if "market for heat, "+heat_dict[temp_level]+", "+heat_dict[power_level]==act["name"]][0]

                if renew_heat_processes!=[]:
                    for proc, amount in zip(renew_heat_processes, amounts):
                        if amount!=0:
                            new_exc = glo_heat_market.new_exchange(input=proc,
                                                   name=proc["name"],
                                                   amount=amount,
                                                   unit=proc["unit"],
                                                   location=proc["location"],
                                                   type='technosphere')
                            new_exc.save()
                    glo_heat_market.save()

                #when no suitable renewable processes: fill with biomethane heat
                elif (temp_level=="LOW" and power_level=="5"):
                    biomethane_acts=[database.get(code) for code in biomethane_codes]
                    for proc in [act for act in biomethane_acts if 'power plant' in act['name']]:
                        new_exc = glo_heat_market.new_exchange(input=proc,
                                                       name=proc["name"],
                                                       amount=1/len([act for act in biomethane_acts if 'power plant' in act['name']]),
                                                       unit=proc["unit"],
                                                       location=proc["location"],
                                                       type='technosphere')
                        new_exc.save()
                    glo_heat_market.save()
                        
                elif (temp_level=="VERY HIGH" and power_level=="2"):
                    biomethane_acts=[database.get(code) for code in biomethane_codes]
                    for proc in [act for act in biomethane_acts if 'industrial furnace' in act['name']]:
                        new_exc = glo_heat_market.new_exchange(input=proc,
                                                       name=proc["name"],
                                                       amount=1/len([act for act in biomethane_acts if 'industrial furnace' in act['name']]),
                                                       unit=proc["unit"],
                                                       location=proc["location"],
                                                       type='technosphere')
                        new_exc.save()
                    glo_heat_market.save()

                #when no suitable renewable processes and (VERY) HIGH temperature: fill with electric resistor heat
                elif (temp_level=="HIGH" and power_level=="3") or (temp_level=="VERY HIGH" and power_level=="3"):
                    resistor_heat_market=[act for act in database if act['name']=="heat production, electric resistance" and act['location']=='GLO'][0]
                    if len(glo_heat_market.technosphere())==0: #if no exchange is yet added
                        new_exc = glo_heat_market.new_exchange(input =resistor_heat_market,
                                                     name  =resistor_heat_name,
                                                     amount=1,
                                                     unit= resistor_heat_market["unit"],
                                                     location= resistor_heat_market["location"],
                                                     type="technosphere")
                        new_exc.save()
                    glo_heat_market.save()
                else:
                    print("Could not create heat market for: ", temp_level, " and ", power_level)
                altered_activities = track_changes(glo_heat_market, altered_activities, 'activity creation')
    print("Set up new heat markets.")

    return(altered_activities)

def get_heat_properties_from_activity(activity):
    """
    Returns temperature and power prooperties of activities.
    
    Args:
               activity: activity
    Returns:
                str:  string with properties, e.g., "0-60 °C, 1-10 MW"
    
    """
    parent_dir = Path.cwd().parent
    
    file = pd.ExcelFile(parent_dir / 'data/raw/heat_processes_allocation.xlsx')
    for sheet in file.sheet_names:
        df=file.parse(sheet)
        fossil_keys=[key.split(",")[1].strip()[1:33] for key in df.iloc[:,5].to_list() if type(key)==str]
        for key in fossil_keys:
            if key==activity["code"]:
                temp_level =sheet[sheet.find('TEMP- ')+len('TEMP- '):sheet.find('|')] #find temperature level
                power_level=str(sheet[len(sheet)-1]) #find power level
                comment=heat_dict[temp_level]+", "+heat_dict[power_level]
                return(comment)
            elif len(key)!=len(activity["code"]):
                print("code length wrong: ", key)
    return(" ")
        
def build_substitition_matrix(database, heat_split, ei_version):
    """
    Builds the substitution matrix with N x M with N: fossil processes and M: fossil-free processes.
    
    Args:       database:               database ei
                heat_split:             dictionary of assigned production share for each renewable class (e.g., solar, heat pump, wood)
                ei_version:             version of ecoinvent, e.g. 3.8
          
    Returns:    fossil_processes:       list of keys of fossil processes
                ff_processes:           list of keys of fossil-free processes
                matrix:                 substitution matrix
    
    """
    print("Importing heat substitution matrix.")

    parent_dir = Path.cwd().parent
    
    print("Allocating fossil heat processes to renewable ones.")
    matrices = []
    file = pd.ExcelFile(parent_dir/'data/raw/heat_processes_allocation.xlsx')
    sheets = file.sheet_names
    for sheet in sheets:
        temp_level, power_level = sheet.replace('TEMP- ','').replace('PL- ','').split('|')

        renew_act_data  = file.parse(sheets[0])[['ff_KEY_{}'.format(ei_version), 'Biofuel/biomass']].dropna(subset=['ff_KEY_{}'.format(ei_version)])
        renew_act_keys  = [(database.name, eval(key)[1]) for key in renew_act_data['ff_KEY_{}'.format(ei_version)].to_list()]
        renew_act_fuels = renew_act_data['Biofuel/biomass'].fillna('none')

        #read fossil heat processes
        fossil_keys    = [(database.name, eval(key)[1]) for key in file.parse(sheet)['fossil_KEY_{}'.format(ei_version)].dropna().to_list()]

        if fossil_keys==[]:
            print('No fossil heat processes to substitute at this level:',heat_dict[temp_level], heat_dict[power_level])
            continue

        heat_market_key = (database.name, get_renewable_heat_market(database, sheet)['code'])

        subst_tuples_at_level = get_heat_process_alternatives(database, fossil_keys, renew_act_keys, renew_act_fuels, heat_market_key, heat_split)
        level_matrix = substituting_tuples_to_matrix(subst_tuples_at_level)
        matrices.append(level_matrix)

    df_matrix = pd.concat(matrices).fillna(0)
    df_matrix.to_excel(parent_dir / 'data/raw/heat_substitution_matrix.xlsx', sheet_name="key")

    fossil_processes, ff_processes, matrix = read_heat_matrix()
    return fossil_processes, ff_processes, matrix

def get_heat_process_alternatives(database, fossil_keys, renew_keys, renew_act_fuels, heat_market_key, heat_split):
    subst_tuples =[]
    for fossil_key in fossil_keys: #find substitutable processes in same location
        fossil_act = database.get(fossil_key[1])
        fossil_act['heat_market'] = heat_market_key
        fossil_act.save()
        
        #try to find suitable renewable process in location
        same_loc_renew_act_keys = [renew_key for renew_key in renew_keys if database.get(renew_key[1])["location"]==fossil_act['location']]
        same_loc_renew_act_fuels= [fuel for renew_key, fuel in zip(renew_keys,renew_act_fuels) if database.get(renew_key[1])["location"]==fossil_act['location']]
        values                  = get_split_of_heat_processes([database.get(key[1])["name"] for key in same_loc_renew_act_keys], heat_split, same_loc_renew_act_fuels)

        #if no suitable reneable process at location, take suitable heat market
        if same_loc_renew_act_keys == []:
            same_loc_renew_act_keys = [heat_market_key]
            values                  = [1]

        sub_tuple=(fossil_key, same_loc_renew_act_keys, values)
        subst_tuples.append(sub_tuple)
    return subst_tuples

def substituting_tuples_to_matrix(subst_tuples_at_level):
    dfs = []
    for sub_tuples in subst_tuples_at_level:
        df = pd.DataFrame(sub_tuples[2], columns=[sub_tuples[0]], index=sub_tuples[1]).T
        dfs.append(df)
    matrix = pd.concat(dfs).fillna(0)
    return matrix

def read_heat_matrix(): 
    parent_dir = Path.cwd().parent
    #read matrix
    df=pd.read_excel(parent_dir / 'data/raw/heat_substitution_matrix.xlsx', sheet_name="key", index_col=0)
    df.index   = [eval(idx) for idx in df.index]
    df.columns = [eval(col) for col in df.columns]
    fossil_processes=df.index.to_list() #list of fossil processes / type: key
    ff_processes    =df.columns.to_list() #list of fossil free processes / type: key
    matrix          =df.values #values without column and row names; as numpy array
    print("Matrix aquired.")
    return fossil_processes, ff_processes, matrix

def assign_heat_technology(name, fuel):
    if 'heat pump' in name.lower():
        return 'heat pump'
    elif 'fuel cell' in name.lower():
        return 'fuel cell'
    elif 'electric resistance' in name.lower():
        return 'electric'
    elif 'straw' in name.lower():
        return 'straw'
    elif 'chips' in name.lower() or 'pellet' in name.lower() or 'chips' in fuel:
        return 'wood chips'
    elif 'wood'in name.lower() or 'log' in name.lower():
        return 'wooden logs'
    elif 'biogas' in name.lower() or fuel=='biogas':
        return 'biogas'
    elif 'biomethane' in name.lower() or fuel=='biomethane':
        return 'biomethane'
    elif 'solar' in name.lower():
        return 'solarthermal'
    elif ('waste' in name.lower() or 'sludge' in name.lower() or 'bagasse' in name.lower() or 'stalk' in name.lower()) and 'reuse' not in name:
        return 'waste'
    elif ('coal' in name.lower() or 'lignite' in name.lower() or 'anthracite' in name.lower()) and 'coal gas' not in name.lower() and 'pulverized' not in name.lower() and 'briquettes' not in name.lower():
        return 'coal'
    elif ('natural gas' in name.lower() or 'propane' in name.lower()) and 'other than' not in name.lower():
        return 'natural gas'
    elif 'oil' in name.lower() or 'diesel' in name.lower() or 'petrol' in name.lower():
        return 'oil'
    elif 'gas' in name.lower():
        return 'waste gas'
    else:
        raise Exception(name, fuel)


def get_split_of_heat_processes(names, weights, fuels):
    """
    This method assignes each renewable process a production share based on heat_split.
    
    Args:
        names:             names of renewable heat processes
        weights:           dictionary of assigned production share for each renewable class (e.g., solar, heat pump, wood)
        fuels:             energy carrier of heat processes
    
    Returns:
        values:            production share value for each process in new_act_names
    """
    if len(names)!=len(fuels):
        raise Exception('Heat process names and fuels unequal length:{}, {}'.format(names, fuels))
    
    df =pd.DataFrame(zip(names, fuels))
    df['classification'] = [assign_heat_technology(name, fuel) for name, fuel in zip(names, fuels)]
    df['weight']         = [weights[clas] for clas in df['classification']]
    df['N of class']     = [len(df[df['classification']==clas]) for clas in df['classification']]
    df['split']          = df['weight']/df['N of class']
    df['split']          = df['split']/sum(df['split'] )
    return list(df.split)

def get_renewable_heat_market(database, sheet_name):
    """
    Returns the heat market that correlates to the temperature level and power level indicated in the sheet name.
    
    Args:           database:          database to search in
                    sheet_name:        name of excel sheet
                    
    Returns:        heat_act:          heat market activity
    """
    
    temp_level =sheet_name[sheet_name.find('TEMP- ')+len('TEMP- '):sheet_name.find('|')]
    power_level=sheet_name[len(sheet_name)-1]
    
    heat_act=[act for act in database if act["name"]=="market for heat, "+heat_dict[temp_level]+", "+heat_dict[power_level]][0]
    return heat_act

def scale_heat_exchanges(database, fossil_reduction_factor, fossil_processes, ff_processes, matrix, altered_activities):
    """
    This adds fossil free heat production processes to activities using heat.

    For the selected location all heat-consuming activities are altered, meaning fossil free heat production processes are added.

    Args:
        database: the database which will be treated
        fossil_reduction_factor: 0: all fossil processes are removed, 1: no fossil process is removed
        matrix: describes which fossil free heat process is added and which fossil heat process is scaled down (ff_processes, fossil_processes)
        fossil_processes: list of fossil heat processes
        ff_processes: list of fossil free processes
        altered_activities: dictionary where newly created and altered activities are stored

    Returns:
        Updated dictionary of altered activities
    """
    print("Looking for heat consuming processes...")

    heat_using_act_codes=[]
    fossil_process_input_codes=[]

    for act in database: #looping trough the database
        exc_key=[(database.name, exc.input["code"]) for exc in act.technosphere()] #all technosphere exchanges as 
        set_A, set_B = set(exc_key), set(fossil_processes) 

        if len(set_A.intersection(set_B))>0: #if fossil heat process in activities exchanges
            heat_using_act_codes.append(act["code"])
            match_codes=[key[1] for key in set_A.intersection(set_B)]
            fossil_process_input_codes+=match_codes

    #get fossil heat markets
    fossil_heat_market_codes = [act['code'] for act in database if 'market for heat,' in act['name'] and 'biomethane' not in act['name'] and '°C' not in act['name'] and 'reuse' not in act['name']]
                        
    #add fossil free exchange to heat using activity
    print("Found {0} activities to treat.".format(len(heat_using_act_codes+fossil_heat_market_codes)))
    for code in tqdm(heat_using_act_codes+fossil_heat_market_codes):
        heat_using_act = database.get(code)
        for exc in heat_using_act.technosphere():
            if exc.input['code'] in fossil_process_input_codes:
                heat_market = database.get(exc.input['heat_market'][1])
                new_exc = heat_using_act.new_exchange(input =heat_market,
                                                     name  =heat_market['name'],
                                                     amount=exc['amount']*(1-fossil_reduction_factor),
                                                     unit= heat_market["unit"],
                                                     location= heat_market["location"],
                                                     type="technosphere")
                new_exc.save()

                # scale down fossil heat
                exc['amount']*=fossil_reduction_factor
                exc.save()

                heat_using_act.save()
        heat_using_act.save()
        altered_activities = track_changes(act, altered_activities, 'scaling')
            
    print("Scaled heat exchanges.")    
    return altered_activities

def get_fossil_free_heat_process(database, fossil_process_key, fossil_processes, ff_processes, matrix):
    """
    Allocates a fossil heat process to one or multiple fossil-free heat processes and the split of these.
    
    Args:     database:             database to find fossil-free process
              fossil_process_key:   key of fossil process
              fossil_processes:     list of keys of fossil processes
              ff_processes:         list of keys of fossil-free processes
              matrix:               substitution matrix
    
    Returns:  ff_process:           fossil-free processes as key
              split:                substitution split of fossil-free processes
              
    
    """
    row_idx   = fossil_processes.index(fossil_process_key) #find row of fossil process in matrix
    clm_idcs  = indices(list(matrix[row_idx, :]),0, '>') #get columns with fossil free processes
    ff_process= [database.get(ff_processes[idx]) for idx in clm_idcs] #get associated fossil free process
    split     = list([matrix[row_idx, idx] for idx in clm_idcs]) #get percentage if multiple processes
    return ff_process, split
                                               
def add_biocoke_market(database, altered_activities, biosphere3):
    """
    Adds a market for biocoke. The market is based on the production of coke in DE (coking), however hard coal is replaced by charcoal.
    
    Args:       database:     databased in which the market is added
                altered_activities: 
    """
    biocoke_market_code=uuid.uuid4().hex
    if "market for biocoke" not in [act["name"] for act in database]:
        coking=[act for act in database if act["name"]=="coking" and act["location"]=="RoW" and act["unit"]=="megajoule"][0]
        biocoke=coking.copy()
        
        biocoke["name"]="market for biocoke"
        biocoke["reference product"]="biocoke"
        biocoke["location"]="GLO"
        biocoke["code"]=biocoke_market_code
        
        for exc in [exc for exc in biocoke.technosphere() if exc.input["reference product"]=="hard coal"]:
            exc.delete() #delete hard coal input
        
        amount=sum([exc.amount for exc in coking.technosphere() if exc.input["reference product"]=="hard coal"])
        
        charcoal=[act for act in database if act["name"]=="market for charcoal" and act["location"]=="GLO"][0] #get charcoal
        biocoke.new_exchange(input = charcoal, #add charcoal
                   name  =charcoal['name'],
                   amount=amount,
                   unit  =charcoal["unit"],
                   type  ='technosphere').save()
        
        altered_activities = fossil_to_nonfossil_biosphere_flows(altered_activities, biocoke, biosphere3, 0)
        
        for exc in biocoke.exchanges(): # alter output to self
            exc["output"]= (database.name, biocoke['code'])
            exc.save()

        biocoke.save()

        altered_activities = track_changes(biocoke, altered_activities, 'activity creation')
        
        
        print("Added market for biocoke.")
        
    charcoal_tar_market_code = uuid.uuid4().hex
    if 'market for charcoal tar' not in [act["name"] for act in database]:
        #create market for charcoal tar 
        coal_tar_market=[act for act in database if act["name"]=="market for coal tar" and act['location']=='GLO'][0]
        charcoaltar=coal_tar_market.copy()
        
        charcoaltar['name'] = 'market for charcoal tar'
        charcoaltar['reference product'] = 'charcoal tar'
        charcoaltar['location'] = 'GLO'
        charcoaltar['code'] = charcoal_tar_market_code
        
        charcoaltar.save()
        
        coal_tar_amounts_and_locations = [(exc.amount, exc.input['location']) for exc in coal_tar_market.technosphere()
                                                               if exc.input['reference product']=='coal tar']
        
        #create charcoal tar production
        coal_tar_productions = [act for act in database if act['name']=='coking' and act['reference product']=='coal tar']
        charcoal=[act for act in database if act["name"]=="market for charcoal" and act["location"]=="GLO"][0] #get charcoal
        charcoal_tar_productions = []
        for coal_tar_production in coal_tar_productions:
            charcoal_tar_production = coal_tar_production.copy()

            charcoal_tar_production["reference product"]="charcoal tar"
            charcoal_tar_production["code"]=uuid.uuid4().hex

            #change hard coal input to charcoal input
            for exc in [exc for exc in charcoal_tar_production.technosphere() if exc.input["reference product"]=="hard coal"]:
                exc['input'] = charcoal
                exc.save()

            charcoal_tar_production.save()
            
            altered_activities = track_changes(charcoal_tar_production, altered_activities, 'activity creation')
            altered_activities = fossil_to_nonfossil_biosphere_flows(altered_activities, charcoal_tar_production, biosphere3, 0)
    
            charcoal_tar_productions.append(charcoal_tar_production)
        
        #change inputs to market for charcoal tar
        for exc in [exc for exc in charcoaltar.technosphere() if exc.input['reference product']=='coal tar']:
            if exc.input['location'] in [act['location'] for act in charcoal_tar_productions]:
                production = [act for act in charcoal_tar_productions if act['location']==exc.input['location']][0]
                
                exc['input'] = production
                exc.save()
        
        charcoal_tar_amount = sum([exc.amount for exc in charcoaltar.technosphere() if exc.input['reference product']=='charcoal tar'])     
        if charcoal_tar_amount<1: #balance to 1
            for exc in charcoaltar.technosphere():
                if exc.input['reference product']=='charcoal tar':
                    exc['amount']/=charcoal_tar_amount
                elif exc.input['name']=='rare earth oxides production, from rare earth oxide concentrate, 70% REO':
                    exc['amount']=0
                exc.save()
                
        altered_activities = track_changes(charcoaltar, altered_activities, 'activity creation')
        print("Added market for charcoal tar.")
            
    return altered_activities


def treat_heat_markets(database, biosphere3, fossil_reduction_factor, heat_split, electricity_locations, ei_version, altered_activities):
    """
    This substitutes fossil heat production processes with renewable/fossil free heat producing processes.

    The fossil_reduction_factor specifies to what degree fossil processes are replaced (0: all, 1: none).

    Args:
        database:                       the database which will be treated
        biosphere3:                     biosphere3 database with biosphere flows
        fossil_reduction_factor:        0: all fossil processes are removed, 1: no fossil process is removed
        altered_activities:             dictionary where newly created and altered activities are stored
        heat_split:                     mode split of heat generation

    Returns:
        Updated dictionary of altered activities
    """
    print("Treating heat markets...")
    if fossil_reduction_factor == 1:
        print('Fossil reduction factor for heat is 1, thus no changes in the heat markets are made.')
        return altered_activities\

    import_heat_classes()
    import_heat_keywords()
    input_map = import_input_map()

    altered_activities=heat_markets_setup(database=database, database_bio=biosphere3,
                       fossil_reduction_factor=fossil_reduction_factor, heat_split=heat_split,
                                          electricity_locations= electricity_locations,
                                          ei_version = ei_version, input_map=input_map, 
                                          altered_activities=altered_activities)
    
    fossil_processes, ff_processes, matrix=build_substitition_matrix(database=database, heat_split=heat_split, ei_version=ei_version)

    altered_activities =scale_heat_exchanges(database=database, 
                                            fossil_reduction_factor=fossil_reduction_factor,
                                            fossil_processes=fossil_processes, ff_processes=ff_processes,
                                            matrix=matrix, altered_activities=altered_activities)
    
    
    print("------------------------------------")       
    print("Heat processes defossilized!")
    print("------------------------------------")  
    
    return altered_activities