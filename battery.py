import pandas as pd
from mip import Model, xsum, maximize, INTEGER


def tidy_prices(path='/Users/hs/Downloads/EPEX_Market_Overview.csv'):
    col_dict = {'Start Time (BST)':'datetime',
                'Day Ahead Price (EPEX) (?/MWh)':'EPEX_HR',
                'Day Ahead Price (Nordpool) (?/MWh)':'Nordp_HR',
                'HH RPD WAP (?/MWh)':'HH_EPEX_wap',
                'Latest HH Trade (?/MWh)':'last_trade_epex'}

    df = pd.read_csv(path, parse_dates=['Start Time (BST)'])[col_dict.keys()].rename(columns=col_dict)

    return df

class Battery:
    def __init__(self, asset_params:dict, markets:list, data:pd.DataFrame):
        self.params=asset_params
        self.market_names=markets
        self.data=data
        self.markets={}
        self.mdl=Model()
        self.opt_df=pd.DataFrame()

    def set_up_model(self):

        self.mdl.add_var('soc', lb=0, ub=1)

        self.mdl.add_var('power', lb=0, ub=1)

        for side in ['buy', 'sell']:
            for mkt in self.market_names:
                self.mdl.add_var(f'{mkt}-{side}',
                                 var_type=INTEGER,
                                 ub= 0 if side=='buy' else 1,
                                 lb= -1 if side=='buy' else 0)

    def make_df_opt(self, time_index: pd.DatetimeIndex):
        self.opt_df = self.data.loc[time_index]

    def set_up_objective(self):
        self.mdl.objective = xsum(
                                    (
                                    self.mdl.markets[f'{mkt}-buy'][p] *
                                    self.opt_df[f'{mkt}-price'][p] *
                                    self.opt_df[f'{mkt}-avbl'][p]
                                    +
                                    self.mdl.markets[f'{mkt}-sell'][p] *
                                    self.opt_df[f'{mkt}-price'][p] *
                                    self.opt_df[f'{mkt}-avbl'][p]

                                     for mkt in self.market_names
                                     for p in range(self.hrzn)
                                    )
                                      )


if __name__ == "__main__":
    data_input=tidy_prices()

