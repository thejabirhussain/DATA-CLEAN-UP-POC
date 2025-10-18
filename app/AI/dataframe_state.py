import pandas as pd
from typing import Optional


class DataFrameState:
    def __init__(self):
        self.current_df: Optional[pd.DataFrame] = None

    def set_dataframe(self, df: pd.DataFrame):
        self.current_df = df

    def update_dataframe(self, df: pd.DataFrame):
        self.current_df = df

    def get_dataframe(self) -> Optional[pd.DataFrame]:
        return self.current_df

    def has_dataframe(self) -> bool:
        return self.current_df is not None
