from __future__ import annotations

# Ordered grid axes expected by QuantLib SwaptionVolatilityMatrix.
EXPIRY_LABELS: list[str] = ["1m", "3m", "6m", "1y", "2y", "3y", "5y", "10y"]
TAIL_LABELS: list[str] = ["1y", "2y", "5y", "10y", "20y", "30y"]

# GS Swaption Vol Dataset coverage.
# NOTE: v1 ships with USD-SOFR-1D coverage only; additional curves can be
# added by extending this mapping without touching query/value code.
ASSET_IDS_MAP: dict[str, dict[str, str]] = {
    "USD-SOFR-1D": {
        "MA0940P64670DMBN": "3m 2y",
        "MA1FNC36DEFHVN2C": "1y 30y",
        "MA2NTGZAVD2MJP7H": "6m 1y",
        "MA3YAP9YTBN0HAM4": "1y 10y",
        "MA445SXEHARX50R9": "10y 1y",
        "MA49ECK032PJTC8J": "3m 10y",
        "MA4ENNPH4E0Y1SSM": "1y 20y",
        "MA58YBVZARCPHEZA": "3y 10y",
        "MA5XPSACC0MJYCVF": "2y 30y",
        "MA6S945RQJGNN9N6": "3y 30y",
        "MA86TN5S1MCAYV43": "5y 2y",
        "MA93T6K8G03JTG3Z": "6m 2y",
        "MA955FBZD7B0P4J3": "3y 5y",
        "MA95VH73S1NCG53X": "2y 1y",
        "MA9QTHX2YEJYXW1F": "2y 5y",
        "MA9SMXP1VBEY5Q3X": "2y 2y",
        "MAB9NBVXX9P4REE8": "1m 1y",
        "MAC4P6MFTTSS0AMC": "5y 10y",
        "MAD3S4WCWZ9QY1CV": "10y 20y",
        "MADBWWZQJ41SV6KN": "1m 10y",
        "MAEGWWZD5Y56JDB4": "5y 5y",
        "MAEY83EK3S0C8S9J": "1y 2y",
        "MAF5ZTP4B6V0Y1FV": "10y 30y",
        "MAFTGRYQ76G5Z30N": "1m 20y",
        "MAFWD8SAF0AAJS3M": "3m 5y",
        "MAH06A6NF31G9RK8": "6m 10y",
        "MAH1GBR0EJV7B1H7": "3m 30y",
        "MAM29DEGNCFFFMGH": "1m 30y",
        "MAME8C0CR5348J9H": "1m 5y",
        "MAMFQNGQMCV5AXEY": "2y 20y",
        "MAMG0AVEH23DQKY8": "3m 20y",
        "MAMXHY0DRCYAJPQM": "3y 20y",
        "MAN2M6FKDSKMM3DK": "1y 1y",
        "MAN736YYV00W3S9W": "3m 1y",
        "MAN86DZD69G4XYR0": "5y 30y",
        "MAPH3C6ANDKXS3KB": "10y 10y",
        "MAPXN9T73JW9REBY": "10y 5y",
        "MASBTVCRWKN3X0E9": "1m 2y",
        "MASJFF197P5KZ9MZ": "3y 2y",
        "MATJX9AX10WZQ88J": "10y 2y",
        "MATK1QVZQ26CV1K1": "3y 1y",
        "MATNZV1K28V2G452": "5y 20y",
        "MAW77GWPT9HN67QM": "5y 1y",
        "MAW8NHDM5GHN4CMN": "6m 20y",
        "MAWJCBSN5NF4HTHJ": "1y 5y",
        "MAWTFMFSHNRGHSG7": "6m 30y",
        "MAYKPCJKVA8ACJZN": "2y 10y",
        "MAZECH8T2R0KD91B": "6m 5y",
    }
}

