from enum import Enum


class QuikVolCalulatorAssetClassEventTarget(Enum):
    Agriculture = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl0$lbProductGroup"
    Cryptocurrencies = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl1$lbProductGroup"
    Energy = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl2$lbProductGroup"
    Equities = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl3$lbProductGroup"
    FX = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl3$lbProductGroup"
    Rates = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl5$lbProductGroup" 
    Metals = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$lvGroups$ctrl6$lbProductGroup"


class QuikVolCalulatorContractEventTarget(Enum):
    SR3 = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl0$lbProduct"
    US = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl1$lbProduct"
    TY = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl2$lbProduct"
    FV = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl3$lbProduct"
    TU = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl4$lbProduct"

    CL = "ucViewControl_IntegratedCalculator$ucSimpleCalc$ucProductNavigator$ucProductSelector$ucProductFamilies$lvProductFamilies$ctrl0$ucProducts$lvProducts$ctrl0$lbProduct"