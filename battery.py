import pandas as pd
from mip import Model, xsum, maximize, INTEGER, CONTINUOUS
from plotly.subplots import make_subplots

def tidy_prices(path='/Users/hs/Downloads/EPEX_Market_Overview.csv'):
    col_dict = {'Start Time (BST)':'datetime',
                'Day Ahead Price (EPEX) (?/MWh)':'EPEX_HR',
                'Day Ahead Price (Nordpool) (?/MWh)':'Nordp_HR',
                'HH RPD WAP (?/MWh)':'HH_EPEX_wap',
                'Latest HH Trade (?/MWh)':'last_trade_epex'}

    df = pd.read_csv(path, parse_dates=['Start Time (BST)'],dayfirst=True)[col_dict.keys()].\
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
        self.opt_df=pd.DataFrame(data={'datetime':pd.date_range(start='2019-07-25', periods=self.hrzn, freq='30T')})
        self.start_soc=0.5
        self.set_up_markets()
        self.add_costs()
        self.set_up_batt_variables()
        self.add_batt_constraints()

    def set_up_markets(self):
        for mkt in self.market_names:
            for side in ['buy', 'sell']:
                mkt_name=f'{mkt}-{side}'
                self.opt_df[mkt_name] = [self.mdl.add_var(name=f'{mkt_name}({i})',
                                                          var_type=CONTINUOUS,
                                                          ub= 0 if side=='buy' else 1,
                                                          lb= -1 if side=='buy' else 0)
                                         for i in range(self.hrzn)]
            self.opt_df[f'{mkt}-price'] = 1 # doing this to get updated later

    def set_up_batt_variables(self):

        self.opt_df['soc'] = [self.mdl.add_var(f'soc({p})', lb=self.params['min_soc'], ub=self.params['max_soc'])
                              for p in range(self.hrzn)]

        self.opt_df['export'] = [self.mdl.add_var(f'export({p})', lb=0, ub=self.params['cap'])
                                 for p in range(self.hrzn)]

        self.opt_df['import'] = [self.mdl.add_var(f'import({p})', lb=-self.params['cap'], ub=0)
                                 for p in range(self.hrzn)]

    def add_batt_constraints(self):
        # fixme: markets sum to > more than capacity
        self.mdl += self.opt_df['soc'].loc[0]==self.start_soc , 'start_soc'
        self.mdl += self.opt_df['soc'].loc[self.hrzn-1]==0.5 , 'end_soc'

        for p in range(self.hrzn-1):
            self.mdl += self.opt_df['soc'][p+1] == self.opt_df['soc'][p] - (self.opt_df['export'][p]+self.params['eff']*self.opt_df['import'][p])/2 , 'soc_update_rule'

        for mkt in self.market_names:
            self.mdl += self.opt_df[f'{mkt}-buy'][self.hrzn-1] == 0,  f'{mkt}-no_last_buy'
            self.mdl += self.opt_df[f'{mkt}-sell'][self.hrzn-1] == 0, f'{mkt}-no_last_sell'

            self.mdl += self.opt_df[f'{mkt}-buy'][0] == 0,  f'{mkt}-no_last_buy'
            self.mdl += self.opt_df[f'{mkt}-sell'][0] == 0, f'{mkt}-no_last_sell'

            for p in range(self.hrzn):
                self.mdl += (self.opt_df['import'][p] + self.opt_df['export'][p]) == (self.opt_df[f'{mkt}-buy'][p] + self.opt_df[f'{mkt}-sell'][p]), 'no_imbal_rule'


    def update_df_opt(self, start):
        self.opt_df['datetime'] = pd.date_range(start=start, periods=self.hrzn, freq='30T')
        for mkt in self.market_names:
            self.opt_df[f'{mkt}-price'] = self.data[mkt][self.opt_df['datetime']].fillna(method='bfill').values

    def add_costs(self):
        # todo: could make these time varying
        self.opt_df['import_costs'] = 25
        self.opt_df['export_costs'] = 0
        self.opt_df['avlbl'] = 1

    def set_up_objective(self):
        # todo check that the objective coefficients change when the proper prices get added in
        self.mdl.objective = maximize(
                                        xsum(
                                            self.opt_df[f'{mkt}-buy'][p] *
                                            self.opt_df[f'{mkt}-price'][p] *
                                            self.opt_df['avlbl'][p]
                                            +
                                            self.opt_df[f'{mkt}-sell'][p] *
                                            self.opt_df[f'{mkt}-price'][p] *
                                            self.opt_df['avlbl'][p]

                                            - self.opt_df[f'{mkt}-sell'][p] * 0.001 # trading fees
                                            + self.opt_df[f'{mkt}-buy'][p] * 0.001

                                            - self.opt_df['export_costs'][p]*self.opt_df['export'][p]
                                            + self.opt_df['import_costs'][p]*self.opt_df['import'][p]
                                             for p in range(self.hrzn)
                                             for mkt in self.market_names
                                            )
                                        )

    def make_plot(self):
        fg=make_subplots(rows=3)
        for col in ['export', 'import']:
            fg.add_bar(x=self.opt_df['datetime'],
                       y=[self.opt_df[col][p].x for p in range(self.hrzn)],
                       name=col, row=1, col=1)

        fg.add_scatter(x=self.opt_df['datetime'], y=[self.opt_df['soc'][p].x for p in range(self.hrzn)],
                   name='soc', row=1, col=1)

        for col in self.market_names:
            fg.add_bar(x=self.opt_df['datetime'],
                       y=[self.opt_df[col+'-buy'][p].x for p in range(self.hrzn)],
                       name=col+'-buy', row=2, col=1)

            fg.add_bar(x=self.opt_df['datetime'],
                       y=[self.opt_df[col+'-sell'][p].x for p in range(self.hrzn)],
                       name=col+'-sell', row=2, col=1)

        for col in self.market_names:
            fg.add_scatter(x=self.opt_df['datetime'],
                           y=[self.opt_df[col+'-price'][p] for p in range(self.hrzn)],
                           name=col+'-price', row=3, col=1)
        fg.show()

    def update_soc(self):
        self.mdl.remove(self.mdl.constr_by_name('start_soc'))
        self.start_soc = self.opt_df['soc'][1].x  - (self.opt_df['export'][1].x+self.params['eff']*self.opt_df['import'][1].x)/2
        self.mdl += self.opt_df['soc'].loc[0]==self.start_soc , 'start_soc'

    def run_opt(self, start):
        self.update_df_opt(start)
        self.add_costs()
        self.set_up_objective()
        self.mdl.optimize()
        self.update_soc()
        self.make_plot()

if __name__ == "__main__":
    prms=dict( cap=1,
               str=1,
               eff=.89,
               max_soc=0.95,
               min_soc=0.05,
            )
    df=tidy_prices()
    hermitage=Battery(asset_params=prms, data=df)
    for k in range(1):
        hermitage.run_opt(start=df.index[2350+k])

