from datetime import datetime
import bw2data as bd
import bw2io as bi
import json
import os
from pathlib import Path
import importlib
import pandas as pd

import electricity as ele
import transport as trans
import heat as heat
import materials as mat
import utils as utl
import checks_and_balances as cab
importlib.reload(trans)
importlib.reload(heat)
importlib.reload(utl)
importlib.reload(cab)
importlib.reload(ele)
importlib.reload(mat)
from electricity import treat_electricity_markets
from transport import create_passenger_vehicles, create_lorries, delete_duplicates_in_carculator_db, add_new_diesel_market, treat_transport
from heat import add_biocoke_market, treat_heat_markets
from materials import treat_other_processes
from utils import migrate_exchanges, import_fossil_identifiers, import_emission_factors, import_electrifiable_processes, import_synfuel_dict, import_not_electrifiable_fuels, import_fossil_refinery_processes, import_not_electrifiable_processes, import_group_locations
from checks_and_balances import checks_and_balances, get_change_report

class FossilfreeDatabase:
    def __init__(
        self,
        ei_version: str = "3.8",
        new_db_name: str = 'ecoinvent-3.8_fossilfree',
        electricity_location_string=None,
        transport_location='GLO',
        fossil_electricity_reduction_factor: float = 0.0,
        transformation_losses: float = 0.01,
        phi: dict = None,
        numb_cycles: int = 5000,
        discharge_depth: float = 0.8,
        nu_turnaround: float = 0.75,
        d: float = 0.26,
        lorry_type_split: dict = None,
        passenger_car_type_split: dict = None,
        truck_year: list = [2020],
        car_year: list = [2020],
        rail_fossil_reduction_factor: float = 0.0,
        aircraft_fossil_reduction_factor: float = 0.0,
        waterway_fossil_reduction_factor: float = 0.0,
        road_fossil_reduction_factor: float = 0.0,
        fossil_heat_reduction_factor: float = 0.0,
        heat_split: dict = None,
        electricity_split: dict = None,
        synfuel_split_dict: dict = None,
        materials_fossil_reduction_factor: float = 0.0
    )-> None:
        #check electricity market locations
        if isinstance(electricity_location_string, str):
            self.electricity_location_string = [electricity_location_string]
        elif isinstance(electricity_location_string, list) and all(isinstance(item, str) for item in electricity_location_string):
            self.electricity_location_string = electricity_location_string
        elif electricity_location_string is None:
            self.electricity_location_string = ["all markets"]
        else:
            raise TypeError("electricity_location_string must be a string or a list of strings")

        #check lorry locations
        if isinstance(transport_location, str):
            self.lorry_locations = transport_location
        else:
            raise TypeError("transport_location must be a string")

        self.ei_version               = ei_version
        self.new_db_name              = 'ecoinvent-{}-cutoff_fossilfree'.format(ei_version)
        self.f_e                      = fossil_electricity_reduction_factor
        self.transf_loss              = transformation_losses
        self.phi                      = {'battery': 0.2, 'h2': 0.01,'pumped': 0.09}
        self.numb_cycles              = numb_cycles
        self.discharge_depth          = discharge_depth
        self.nu_turnaround            = nu_turnaround
        self.d                        = d
        self.lorry_type_split         = {'BEV':  0.8,
                                         'FCEV': 0.1,
                                         'ICE':  0.1,
                                        }
        self.passenger_car_type_split = {'BEV':  0.8,
                                         'FCEV': 0.1,
                                        ' ICE':  0.1,
                                        }
        self.car_year                 = car_year
        self.truck_year               = truck_year
        self.f_rail                   = rail_fossil_reduction_factor
        self.f_air                    = aircraft_fossil_reduction_factor
        self.f_road                   = road_fossil_reduction_factor
        self.f_water                  = waterway_fossil_reduction_factor
        self.f_h                      = fossil_heat_reduction_factor
        self.heat_weights             = {"solarthermal": 0.15, 
                                         "heat pump":    0.69, 
                                         "biomethane":   0.05, 
                                         "biogas":       0.05, 
                                         "wood chips":   0.005,
                                         "wooden logs":  0.005,
                                         "straw":        0.005,
                                         "waste":        0.005,
                                         "electric":     0.03,
                                         "fuel cell":    0.01
                                         }
        self.electricity_split        = {"PV":            0.9,
                                         "Wind onshore":  0.02,
                                         "Wind offshore": 0.03,
                                         "Hydro":         0.005,
                                         "Geothermal":    0.005,
                                         "Biomass":       0.005,
                                         "Nuclear":       0.005,
                                         "Solar":         0.03}
        self.synfuel_split_dict       = {"biogen": 0.1, "syngen": 0.9}
        self.f_mat = materials_fossil_reduction_factor

    def load_parameters(self, path=Path.cwd().parent, filename='input_parameters_v2.xlsx'):
        df = pd.read_excel(path / filename)

        # asigning the inputs to variables
        ei_version                  = str(df.iloc[0, 1])
        electricity_location_string = str(df.iloc[1, 1])
        transport_location             = str(df.iloc[2, 1])
        fossil_electricity_reduction_factor  = float(df.iloc[3, 1])
        transformation_losses       = float(df.iloc[4, 1])
        phi = {'battery': float(df.iloc[6, 1]),
                'h2':     float(df.iloc[7, 1]),
                'pumped': float(df.iloc[8, 1])
                }
        nc              = int(df.iloc[9, 1])
        discharge_depth = float(df.iloc[10, 1])
        nu_turnaround   = float(df.iloc[11, 1])
        d               = float(df.iloc[12, 1])
        
        pv         = float(df.iloc[14, 1])
        wind_on    = float(df.iloc[15, 1])
        wind_off   = float(df.iloc[16, 1])
        hydro      = float(df.iloc[17, 1])
        geothermal = float(df.iloc[18, 1])
        biomass    = float(df.iloc[19, 1])
        nuclear    = float(df.iloc[20, 1])
        solar      = float(df.iloc[21, 1])
        
        lorry_type_split = {'BEV':  float(df.iloc[23, 1]),
                            'FCEV': float(df.iloc[24, 1]),
                            'ICE':  float(df.iloc[25, 1])
                            }
        passenger_car_type_split = {'BEV':  float(df.iloc[27, 1]),
                                    'FCEV': float(df.iloc[28, 1]),
                                    'ICE':  float(df.iloc[29, 1])
                                    }
        truck_year                       = int(df.iloc[30, 1])
        car_year                         = int(df.iloc[31, 1])
        rail_fossil_reduction_factor     = float(df.iloc[32, 1])
        waterway_fossil_reduction_factor = float(df.iloc[33, 1])
        aircraft_fossil_reduction_factor = float(df.iloc[34, 1])
        road_fossil_reduction_factor     = float(df.iloc[35, 1])
        syngen                           = float(df.iloc[36, 1])
        biogen                           = 1- syngen
        new_db_name                      = str(df.iloc[37, 1])

        fossil_heat_reduction_factor     = float(df.iloc[38,1])
                        
        solarthermal =float(df.iloc[40,1])
        heat_pump    =float(df.iloc[41,1])
        biomethane   =float(df.iloc[42,1])
        biogas       =float(df.iloc[43,1])
        wood_chips   =float(df.iloc[44,1])
        wooden_logs  =float(df.iloc[45,1])
        straw        =float(df.iloc[46,1])
        waste        =float(df.iloc[47,1])
        electric     =float(df.iloc[48,1])
        fuel_cell    =float(df.iloc[49,1])

        materials_fossil_reduction_factor = float(df.iloc[50,1])
    
        # check input
        supported_versions = ['3.8', '3.9', '3.9.1']
        if ei_version not in supported_versions:
            print('Ecoinvent version {} not supported. Only tested for {}'.format(ei_version, supported_versions))
        assert nc>0
        assert d>0
        assert (discharge_depth>0                      and discharge_depth<=1)
        assert (transformation_losses>=0               and transformation_losses<=1)
        assert (nu_turnaround>0                        and nu_turnaround<=1)
        assert (fossil_electricity_reduction_factor>=0 and fossil_electricity_reduction_factor<=1)
        assert (rail_fossil_reduction_factor>=0        and rail_fossil_reduction_factor<=1)
        assert (waterway_fossil_reduction_factor>=0    and waterway_fossil_reduction_factor<=1)
        assert (aircraft_fossil_reduction_factor>=0    and aircraft_fossil_reduction_factor<=1)
        assert (road_fossil_reduction_factor>=0        and road_fossil_reduction_factor<=1)
        assert (fossil_heat_reduction_factor>=0        and fossil_heat_reduction_factor<=1)
        assert (materials_fossil_reduction_factor>=0   and materials_fossil_reduction_factor<=1)

        #check electricity market locations
        if isinstance(electricity_location_string, str):
            self.electricity_location_string = [electricity_location_string]
        elif isinstance(electricity_location_string, list) and all(isinstance(item, str) for item in electricity_location_string):
            self.electricity_location_string = electricity_location_string
        elif electricity_location_string is None:
            self.electricity_location_string = ["all markets"]
        else:
            raise TypeError("electricity_location_string must be a string or a list of strings")

        #check lorry locations
        if isinstance(transport_location, str):
            self.transport_location = transport_location
        else:
            raise TypeError("transport_location must be a string or a list of strings")

        phisum = sum(phi.values())
        if phisum >= 1:
            for phi_type in phi:
                lorry_type_split[phi_type] = float(lorry_type_split[phi_type] / phisum)
    
        testsum = sum(lorry_type_split.values())
        if testsum <= 0:
            raise Exception('Lorry type split sum is negative', lorry_type_split)
        if testsum != 1:
            print('Lorry type split sum unequal 1.0. Will balance to 1.0.', lorry_type_split)
            for lorry_type in lorry_type_split:
                lorry_type_split[lorry_type] = float(lorry_type_split[lorry_type] / testsum)
    
        testsum_pas = sum(passenger_car_type_split.values())
        if testsum_pas <= 0:
            raise Exception('Lorry type split sum is negative', passenger_car_type_split)
        if testsum_pas != 1:
            print('Passenger type split sum unequal 1.0. Will balance to 1.0.', passenger_car_type_split)
            for typ in passenger_car_type_split:
                passenger_car_type_split[typ] = float(lorry_type_split[typ] / testsum_pas)
            
        if type(car_year)==str:
            car_year=[int(ele.strip()) for ele in car_year.split(",")]
        else:
            car_year=[car_year]

        assert (car_year[0]>=2020 and car_year[0]<=2100)

        if type(truck_year)==str:
            truck_year=[int(ele.strip()) for ele in truck_year.split(",")]
        else:
            truck_year=[truck_year]
        assert (truck_year[0]>=2020 and truck_year[0]<=2100)
        
        heat_weights={"solarthermal": solarthermal, 
                    "heat pump":    heat_pump, 
                    "biomethane":   biomethane, 
                    "biogas":       biogas, 
                    "wood chips":   wood_chips,
                    "wooden logs":  wooden_logs,
                    "straw":        straw,
                    "waste":        waste,
                    "electric":     electric,
                    "fuel cell":    fuel_cell
                    }
        if sum(heat_weights.values())!=1:
            raise Exception("Heat process split sum is not 1. Check inputs.")
        
        if not all([(weight>0) for weight in heat_weights.values()]):
            raise Exception('All heat weights must be positive.', heat_weights)

        if pv+wind_on+wind_off+hydro+geothermal+biomass+nuclear+solar!=1:
            raise Exception("Electricity split sum is not 1. Check inputs.")
        
        electricity_split={"PV":            pv,
                           "Wind onshore":  wind_on,
                           "Wind offshore": wind_off,
                           "Hydro":         hydro,
                           "Geothermal":    geothermal,
                           "Biomass":       biomass,
                           "Nuclear":       nuclear,
                           "Solar":         solar}
        
        if not all([(share>0) for share in electricity_split.values()]):
            raise Exception('All electricity mix shares must be positive.', heat_weights)
        
        if syngen<0 or syngen>1:
            raise Exception('Share of synfuels must be between 0 and 1.', syngen, '\nCheck input.')
        
        synfuel_split_dict={"biogen": biogen,
                            "syngen": syngen}
        
        # update parameters
        self.ei_version               = ei_version
        self.new_db_name              = new_db_name
        self.f_e                      = fossil_electricity_reduction_factor
        self.transf_loss              = transformation_losses
        self.phi                      = phi
        self.discharge_depth          = discharge_depth
        self.nu_turnaround            = nu_turnaround
        self.numb_cycles              = nc
        self.d                        = d
        self.lorry_type_split         = lorry_type_split
        self.passenger_car_type_split = passenger_car_type_split
        self.car_year                 = car_year
        self.truck_year               = truck_year
        self.f_rail                   = rail_fossil_reduction_factor
        self.f_air                    = aircraft_fossil_reduction_factor
        self.f_road                   = road_fossil_reduction_factor
        self.f_water                  = waterway_fossil_reduction_factor
        self.heat_weights             = heat_weights
        self.electricity_split        = electricity_split
        self.synfuel_split_dict       = synfuel_split_dict
        self.f_mat                    = materials_fossil_reduction_factor

    def reference_database_setup(self, ei_version='3.8', project='FFEI', username=None, password=None, biosphere_name = 'biosphere3', system_model='cutoff', biosphere_write_mode='patch'):
        """
        This sets or creates the project & assures the existence of the default database.
    
        Ars:
            ei_version:   ecoinvent version; default database | String: e.g., "ecoinvent 3.7.1", "ecoinvent 3.8"
            db_path   :   filepath to folder with LCI databases needed for FFEI
            project   :   Name of project
    
        Returns:
            biosphere database
            default ecoinvent database
            dictionary to keep track of altered activities (for documentation)
        """
        print('Starting the initiation at ', datetime.now().strftime("%H:%M:%S"))
        altered_activities = {}
        bd.projects.set_current(project)  # Creating/accessing the project
        #bi.bw2setup()  # Importing elementary flows, LCIA methods and some other data
        
        if 'ecoinvent-{}-cutoff'.format(ei_version) not in bd.databases:
            bi.import_ecoinvent_release(
                version=ei_version,
                system_model=system_model,
                username=username, #insert ecoinvent username
                password=password, #insert password
                biosphere_name=biosphere_name,
                biosphere_write_mode=biosphere_write_mode    
            )
        else:
            print('ecoinvent-{}-cutoff already imported.'.format(ei_version))
            
        self.biosphere_db = bd.Database(biosphere_name)
        self.base_db      = bd.Database('ecoinvent-{}-cutoff'.format(ei_version))
        self.altered_activities = {}

        self.add_additional_biosphere_flows()
    
    def add_additional_biosphere_flows(self):
        """
        Adds noise emission flows to biosphere3 database.
        """
        import os

        parent_dir = Path.cwd().parent

        biosphere_db = self.biosphere_db
        with open(parent_dir/'data'/'raw'/"biosphere3_additions.json", "r") as json_file:
            add_bio_data = json.load(json_file)
        for ds in add_bio_data:
            try:
                biosphere_db.get(ds['code'])
            except:
                new_flow = biosphere_db.new_activity(**ds)
                new_flow.save()
    
    def setup_locations(self):
        """
        Lists all locations for electricity markets.
        
        """
        if 'all markets' in self.electricity_location_string:
            electricity_locations = []
            for act in self.base_db:
                if act['location'] not in electricity_locations and ('market for electricity, low voltage' or
                                                                 'market for electricity, medium voltage' or
                                                                 'market for electricity, high voltage') in act['name']:
                    electricity_locations.append(act['location'])
        else:
            electricity_locations = [loc.strip() for loc in self.electricity_location_string.split(',')]
        
        self.electricity_locations = electricity_locations

    def copy_base_db(self, overwrite=False):
        """
        Copies refererence database with name of new fossilfree database.
        """

        if overwrite:
            if self.new_db_name in bd.databases:
                bd.Database(self.new_db_name).deregister()
                print("{} deregistered. Will create new one.".format(self.new_db_name))
            new_db = self.base_db.copy(self.new_db_name)
        elif self.new_db_name not in bd.databases:
            new_db = self.base_db.copy(self.new_db_name)
        else:
            print('Already copied.')
            new_db = bd.Database(self.new_db_name)
        self.fossilfree_db = new_db

    def add_inventories(self, other_db_name):
        """
        Creates carculator and carculator truck databases and merges with database. Also adds bio and synthetic diesel markets and biocoke markets.
    
        """
        
        create_passenger_vehicles(self.car_year, self.fossilfree_db, self.ei_version, self.transport_location)
        create_lorries(self.fossilfree_db, self.truck_year, self.ei_version, self.transport_location)
        
        print("Merged with carculator db and carculator_truck db.")
        
        self.altered_activities = add_new_diesel_market(self.fossilfree_db, self.altered_activities, self.synfuel_split_dict)
        self.altered_activities = add_biocoke_market(self.fossilfree_db, self.altered_activities, self.biosphere_db)
        
        self.merge_with_synfuel_database(other_db_name=other_db_name)
        
        print("Added new diesel market and biocoke market.")

    def merge_with_synfuel_database(self, other_db_name='synfuels'):
        """
        Merges ecoinvent database with synfuel database.
        
        Args:      
                   eidb:         ecoinvent database
                   other_db:     other databases to be merged
        
        """
        parent_dir = Path.cwd().parent
        eidb     = self.fossilfree_db
        ei_version_nr = self.ei_version
        parent_db= eidb.name
        try:
            if other_db_name in bd.databases[parent_db]["merged"]:
                print("Synfuel already in database: ", eidb.name)
                return
            else:
                raise Exception()
        except:
            if other_db_name not in bd.databases:
                try:
                    path = os.path.join(parent_dir /'data'/'raw'/ '{}.xlsx'.format(other_db_name))
                    imp = bi.ExcelImporter(path)
                except:
                    raise Exception('Could not find synfuel database here: {}'.format(parent_dir /'data'/'raw'/ '{}.xlsx'.format(other_db_name)))
                imp.apply_strategies()
                if ei_version_nr!='3.8':
                    new_data = migrate_exchanges(imp.data.copy(), from_version='3.8', to_version=self.ei_version)
                    imp.data = new_data
                imp.match_database(eidb.name, fields=('name','unit','location',"reference product"))
                imp.match_database(self.biosphere_db.name, fields=('name','unit','location'))
                imp.match_database(fields=('name', 'unit', 'location'))
                imp.statistics()
                try:
                    imp.write_database()
                except:
                    imp.write_excel(only_unlinked=True) #unlinked=False export the full list of exchanges
                    raise Exception('Database import failed. See unlinked exchanges')
    
            print("Merging {0} with {1}".format(eidb.name, other_db_name))
            delete_duplicates_in_carculator_db(eidb, other_db_name) #delete duplicates before merging
            bd.utils.merge_databases(parent_db, other_db_name)

        bd.databases[parent_db]["modified"]=str(datetime.now()).replace(" ","T")
        bd.databases[parent_db]["merged"]  =other_db_name
        bd.databases[parent_db]=bd.databases[parent_db]


    def display_parameters(self):
        parameter_df = pd.DataFrame({'values':{key:str(self.__dict__[key]) for key in self.__dict__.keys()}})
        display(parameter_df)

    def load_auxiliary_data(self):
        self.fossil_identifier          = import_fossil_identifiers()
        self.emission_factors           = import_emission_factors()
        self.electrifiable_processes    = import_electrifiable_processes()
        self.synfuel_dict               = import_synfuel_dict()
        self.not_electrifiable_fuels    = import_not_electrifiable_fuels()
        self.fossil_refinery_processes  = import_fossil_refinery_processes()
        self.not_electrifiable_processes= import_not_electrifiable_processes()
        self.grouped_locations          = import_group_locations()

    def defossilize_electricity(self):
        self.altered_activities = treat_electricity_markets(
                                  database = self.fossilfree_db,
                                  locations = self.electricity_locations,
                                  #locations = ['DE', 'FR'],
                                  transformation_losses = self.transf_loss,
                                  phi = self.phi,
                                  numb_cycles = self.numb_cycles,
                                  discharge_depth = self.discharge_depth,
                                  ei_version = self.ei_version,
                                  nu_turnaround = self.nu_turnaround,
                                  d = self.d,
                                  fossil_reduction_factor = self.f_e,
                                  fossil_identifiers = self.fossil_identifier,
                                  altered_activities = self.altered_activities,
                                  electricity_split = self.electricity_split
                                 )

    def defossilize_heat(self):
        self.altered_activities = treat_heat_markets(
                           database = self.fossilfree_db,
                           biosphere3 = self.biosphere_db,
                           fossil_reduction_factor = self.f_h,
                           heat_split = self.heat_weights,
                           electricity_locations = self.electricity_locations,
                           ei_version = self.ei_version,
                           altered_activities = self.altered_activities
                        )

    def defossilize_transport(self):
        self.altered_activities = treat_transport(
                                        database = self.fossilfree_db,
                                        biosphere3 = self.biosphere_db,
                                        car_year = self.car_year,
                                        truck_year = self.truck_year, 
                                        lorry_type_split = self.lorry_type_split,
                                        passenger_car_type_split = self.passenger_car_type_split,
                                        road_fossil_reduction_factor = self.f_road,
                                        rail_fossil_reduction_factor = self.f_rail,
                                        waterway_fossil_reduction_factor = self.f_water,
                                        aircraft_fossil_reduction_factor = self.f_air,
                                        synfuel_dict = self.synfuel_dict,
                                        fossil_identifiers = self.fossil_identifier,
                                        not_electrifiable_fuels = self.not_electrifiable_processes, 
                                        emission_factors_dict = self.emission_factors,
                                        synfuel_split_dict = self.synfuel_split_dict,
                                        ei_version = self.ei_version,
                                        altered_activities = self.altered_activities
                                    )

    def defossilize_other(self):
        self.altered_activities = treat_other_processes(
                                        database = self.fossilfree_db,
                                        biosphere3 = self.biosphere_db,
                                        fossil_reduction_factor = self.f_mat,
                                        synfuel_split_dict = self.synfuel_split_dict,
                                        electricity_locations = self.electricity_locations,
                                        synfuel_dict = self.synfuel_dict,
                                        emission_factors_dict = self.emission_factors,
                                        fossil_identifiers = self.fossil_identifier,
                                        not_electrifiable_fuels = self.not_electrifiable_fuels,
                                        electrifiable_processes = self.electrifiable_processes,
                                        not_electrifiable_processes = self.not_electrifiable_processes,
                                        fossil_refinery_processes = self.fossil_refinery_processes,
                                        grouped_locations = self.grouped_locations,
                                        altered_activities = self.altered_activities
                                        )

    def defossilize_all(self):
        self.defossilize_electricity()
        self.defossilize_heat()
        self.defossilize_transport()
        self.defossilize_other()

    def setup_and_add_inventories(self, project, username, password, overwrite=False):
        self.load_parameters()
        self.setup(project, username, password, overwrite=False)
        self.add_inventories(other_db_name='synfuels')

    def setup(self, project, username, password, overwrite=False):
        self.reference_database_setup(ei_version=self.ei_version,
                            project=project,
                            username=username,
                            password=password)
        self.setup_locations()
        self.copy_base_db(overwrite=overwrite)
        self.load_auxiliary_data()

    def run_checks_and_balances(self):
        print('Run checks and balances.')
        checks_and_balances(db = self.fossilfree_db,
                            biosphere3 = self.biosphere_db, 
                            base_db_name = self.base_db.name)

    def save_change_report(self, path = Path.cwd().parent):
        
        print('Generating change report.')
        change_report  = get_change_report(self.fossilfree_db, self.altered_activities)
        change_report.to_excel(path / 'results' /'change_report.xlsx')
        print('Saved change report under:\n{}'.format(path / 'results' /'change_report.xlsx'))