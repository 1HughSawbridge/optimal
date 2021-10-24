import pandas as pd
from mip import Model, xsum, maximize, INTEGER
from plotly.subplots import make_subplots

def tidy_prices(path='/Users/hs/Downloads/EPEX_Market_Overview.csv'):
    col_dict = {'Start Time (BST)':'datetime',
                'Day Ahead Price (EPEX) (?/MWh)':'EPEX_HR',
                'Day Ahead Price (Nordpool) (?/MWh)':'Nordp_HR',
                'HH RPD WAP (?/MWh)':'HH_EPEX_wap',
                'Latest HH Trade (?/MWh)':'last_trade_epex'}

    df = pd.read_csv(path, parse_dates=['Start Time (BST)'])[col_dict.keys()].\
            rename(columns=col_dict).\
            set_index('datetime')

    return df

class Battery:
    def __init__(self, data:pd.DataFrame, asset_params:dict):
        self.hrzn=48
        self.params=asset_params
        self.market_names=data.columns
        self.data=data
        self.markets={}
        self.mdl=Model()
        self.opt_df=pd.DataFrame(data={'datetime':pd.date_range(start='2019-07-25',periods=self.hrzn,freq='30T')})
        self.start_soc=0.5
        self.set_up_markets()
        self.add_costs()
        self.set_up_batt_variables()
        self.set_up_objective()


    def set_up_markets(self):
        for mkt in self.market_names:
            for side in ['buy', 'sell']:
                mkt_name=f'{mkt}-{side}'
                self.opt_df[mkt_name] =[self.mdl.add_var(name=mkt_name,
                                                         var_type=INTEGER,
                                                         ub= 0 if side=='buy' else 1,
                                                         lb= -1 if side=='buy' else 0)
                                        for i in range(self.hrzn)]
            self.opt_df[f'{mkt}-price'] = 1 # doing this to get overriden later

    def set_up_batt_variables(self):
        # todo we want to have the start SOC fed in as row [-1] somehow, i think add a blank row
        self.opt_df['soc']  =  [self.mdl.add_var('soc', lb=self.params['min_soc'], ub=self.params['min_soc'])
                                for p in range(self.hrzn)]

        self.opt_df['power'] = [self.mdl.add_var('power', lb=-self.params['cap'], ub=self.params['cap'])
                                for p in range(self.hrzn) ]

    def add_batt_constraints(self):
        for p in range(1, self.hrzn):
            self.mdl.add_constr(name='soc_model',
                                lin_expr=self.mdl.soc[p] == self.mdl.soc[p-1] + self.mdl.power[p]/self.params['str'])

            self.mdl.add_constr(name='no_imbal',
                                lin_expr=xsum(
                                    self.mdl.power[p] == self.mdl.var_by_name(f'{mkt}-buy') +
                                                         self.mdl.var_by_name(f'{mkt}-sell')
                                    for mkt in self.market_names)
                                )

    def update_df_opt(self, start):
        self.opt_df['datetime'] = pd.date_range(start=start, periods=self.hrzn, freq='30T')
        for mkt in self.market_names:
            self.opt_df[f'{mkt}-price'] = self.data[mkt].loc[self.opt_df['datetime']]

    def add_costs(self):
        # todo: could make these time varying
        self.opt_df['import_costs'] = 5
        self.opt_df['export_costs'] = 1
        self.opt_df['avlbl'] = 1

    def set_up_objective(self):
        # todo check that the objective coefficients change when the proper prices get added in
        self.mdl.objective = maximize(
                                        xsum(
                                            (
                                            self.opt_df[f'{mkt}-buy'][p] *
                                            self.opt_df[f'{mkt}-price'][p] *
                                            self.opt_df['avlbl'][p]
                                            +
                                            self.opt_df[f'{mkt}-sell'][p] *
                                            self.opt_df[f'{mkt}-price'][p] *
                                            self.opt_df['avlbl'][p]

                                             for mkt in self.market_names
                                             for p in range(self.hrzn)
                                            )
                                        )
                                     )

    def make_plot(self):
        fg=make_subplots()
        for col in ['power', 'soc']:
            fg.add_scatter(x=self.opt_df['datetime'],
                           y=[self.opt_df[col][p].x for p in range(self.hrzn)],
                           name=col)
        fg.show()

    def update_soc(self):
        # todo: make this as a result of the optimisesr
        self.start_soc = 0.5

    def run_opt(self, start):
        self.update_df_opt(start)
        self.mdl.add_constr(name='start_soc',lin_expr=self.mdl.soc[0]==self.start_soc)
        self.add_costs()
        self.mdl.optimize()
        self.update_soc()
        self.make_plot()

if __name__ == "__main__":
    prms=dict(
              cap=1,
              str=1,
              eff=.89,
              max_soc=0.95,
              min_soc=0.05,
            )

    df=tidy_prices()
    hermitage=Battery(asset_params=prms, data=df)
    hermitage.run_opt(start=df.index[0])

