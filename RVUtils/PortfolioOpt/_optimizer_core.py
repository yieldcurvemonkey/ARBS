# -*- coding: utf-8 -*-
"""Mean-variance portfolio optimizer with transaction costs, market impact and constraints.

PROVENANCE. Ported verbatim from ``jpm_pfin/RVPF/optimizer.py`` (author ``jchancer``). ARBS had no
portfolio optimizer, no margin model and no capital model before this; this file is the whole of
that gap. The solver core -- ``mean_variance_one_period``, the three problem formulations, the
constraint composition and the QCQP->SDP recasting, roughly a thousand lines from
``mean_variance_one_period`` down -- is UNCHANGED. Only the pandas-0.x dispatch layer was ported.

WHAT CHANGED, and nothing else:
  * ``pandas.Panel`` (removed in pandas 1.0) -> :class:`RVUtils.PortfolioOpt.panel3d.Panel3D`
  * ``.ix[...]`` (removed) -> ``.loc[...]``
  * ``np.float`` (removed in numpy 1.24) -> ``float``
  * ``dict(list(x.items()) + [...])`` (py2 list semantics) -> ``dict(list(x.items()) + [...])``

KNOWN DEFECT, inherited and flagged rather than silently carried. The author left this comment in
``solve_qcqp_via_sdp_recasting``:

    cvxopt IS RETURNING THAT THE PROBLEM IS INFEASIBLE WITH THESE CONSTRAINTS ADDED.
    HAVEN'T YET IDENTIFIED WHY.

That path is reached only with a non-zero ``market_impact_exponent`` **and** quadratic constraints.
The linear-transaction-cost path -- the one the cross-currency book uses and the one covered by
tests -- does not touch it.

TESTED SURFACE: the unconstrained and box-constrained linear-tcost paths. The quadratic-constraint
and square-root-market-impact paths are ported but untested here; treat them as unproven.
"""

from RVUtils.PortfolioOpt.panel3d import Panel3D, as_panel3d

from abc import abstractmethod
import pandas as pd
import numpy as np
import cvxopt


class Optimizer:

    def __init__(self, config=None, data_object=None):

        self.config = config
        self.data = data_object

    @abstractmethod
    def calculate(self, alphas, risk_model, transaction_costs, initial_holdings=None, constraint_risk_model=None):
        """ method for calculating holdings """

    def build_constraint_structures(self, group_constraints=None, asset_constraints=None, constraint_groups=None,
                                    risk_target=None, tuning_risk_target=None, assets=None):
        """
        takes in lists of constraints and constraint groups parsed from the model configuration and returns
        a dictionary of dictionaries with the top level key being constraint type and the lower level keys
        being weights, lower_bounds, and upper_bounds

        Inputs:
            group_constraints : list of dictionaries, optional
                list of dictionaries where each dictionary is a separate constraint specification. the keys of each
                individual constraint specification are:
                    'type' : string
                        must be one of 'net', 'gross', 'long', 'short', 'net_turnover', 'gross_turnover', 'buys',
                        'sells', or 'quadratic'. these will ultimately specify different types of constraints on
                        (groups of) assets. the bound types mean:
                            net: specify a constraint on the net positions
                            gross: specify a constraint on the gross positions (upper bound only)
                            long: specify a constraint on just the long positions (upper bound only)
                            short: specify a constraint on just the short positions (upper bound only)
                            net_turnover: specify a constraint on the net turnover
                            gross_turnover: specify a constraint on the gross turnover (upper bound only)
                            buys: specify a constraint on just the buys (upper bound only)
                            sells: specify a constraint on just the sells (upper bound only)
                            quadratic: specify a constraint on the variance of a (sub-)portfolio (upper bound only)
                    'group' : string or list
                        if string, it must refer to a list in the constraint_groups input, keyed by this string. if
                        list, it will be a list of strings (which are asset identifiers like "CL Comdty").
                    'upper_bound' : positive float, Series of positive floats, or DataFrame of positive floats, optional
                        upper bound to impose for the constraint. if not specified, 'bound' must be present and will
                        be used instead. if Series or DataFrame with a DatetimeIndex, different upper bounds are
                        assumed to be specified for different points in time, and return structures will be DataFrames
                        for lower_bound and upper_bound and Panel for weights instead of the standard Series and
                        DataFrame respectively
                    'lower_bound' : negative float, Series of negative floats, or DataFrame of negative floats, optional
                        lower bound to impose for the constraint. if not specified, the constraint type accepts lower
                        bounds, and 'bound' is present, the entry for 'bound' will be used instead. if Series or
                        DataFrame with a DatetimeIndex, different lower bounds are assumed to be specified for
                        different points in time, and return structures will be DataFrames for lower_bound and
                        upper_bound and Panel for weights instead of the standard Series and DataFrame respectively
                    'bound' : positive float, Series of positive floats, or DataFrame of positive floats, optional
                        bound to impose for the constraint. if specified, neither upper_bound or lower_bound may be
                        specified, and bound will be used to populate those values as necessary. if Series or DataFrame
                        with a DatetimeIndex, different bounds are assumed to be specified for different points
                        in time, and return structures will be DataFrames for lower_bound and upper_bound and Panel
                        for weights instead of the standard Series and DataFrame respectively
                    'weights' : list, array, Series, or DataFrame, optional
                        optional weights to apply to asset weights before imposing the constraint. i.e. instead of
                        the constraint applying on just the raw asset weights produced by the optimizer, constraints
                        will apply instead on the asset weights multiplied by the weights passed in here. default is
                        all 1s, and the numbers can be positive or negative. i.e. one could constrain arbitrary
                        (sub-)portfolios or spreads between assets. if DataFrame with a DatetimeIndex, different
                        weights are assumed to be specified for different points in time, and return structures will
                        be DataFrames for lower_bound and upper_bound and Panel for weights instead of the standard
                        Series and DataFrame respectively
                    'scale' : boolean, optional
                        if risk_target and tuning_risk_target are passed in, bounds passed in will be multiplied by
                        risk_target / tuning_risk_target if this parameter is set to True. default is True.
            asset_constraints : list of dictionaries, optional
                list of dictionaries where each dictionary is a separate constraint specification. the keys of each
                individual constraint specification are identical to the above. the difference between asset
                constraints and group constraints are that the bounds for asset constraints are applied individually
                to each asset in the list specified in the 'group' entries (or the assets pointed to in the
                constraint_groups dict by the 'group' entries) rather than the bounds applying to the
                (optionally 'weights'ed) group as a whole
            constraint_groups : dictionary, optional
                dictionary with keys equal to strings (which are arbitrary group identifiers like "energies"), and
                values which are lists of strings (which are asset identifiers like "CL Comdty"). if no constraint
                groups are defined, 'group' entries in the group_constraints and asset_constraints structures must
                use lists of assets rather than group identifiers
            risk_target and tuning_risk_target: floats, optional
                if and only if both of these are specified, all bounds for scaleable constraints (all constraints
                where 'scale' parameter is not set to False) will be multiplied by risk_target / tuning_risk_target.
                this is useful if you tune the constraint bounds using one particular risk target during research,
                but then want to change this risk target at some point while running the model live and don't want to
                have to go back and retune all constraints at the new risk target
            assets : list of strings, optional
                the full set of assets over which constraints are defined. if not set, it will be derived from all
                assets that exist in any of the group_constraints, asset_constraints, or constraing_groups entries
                useful for ensuring that the weights entries in the output dictionary cover the full universe of
                assets including any assets for which constraints have not been specified.

        Output:
            constraint_dict : dictionary of dictionaries
                primary key is the bound type and secondary keys are in the following structure:
                    'net' :
                        'upper_bounds' : Series
                            upper bounds for net constraints
                        'lower_bounds' : Series
                            lower bounds for net constraints
                        'weights' : DataFrame
                            weights to apply before imposing the net constraint, axes are [constraint, asset] where
                            asset columns have been set to the same list for all constraints
                    'gross' :
                        'upper_bounds' : Series
                            upper bounds for gross constraints
                    ...
        """

        # set default group and asset constraints
        if group_constraints is None:
            group_constraints = []
        if asset_constraints is None:
            asset_constraints = []
        if constraint_groups is None:
            constraint_groups = {}

        # make sure constraints are not defined for groups that are not defined
        if len(set([x['group'] for x in group_constraints
                    if not isinstance(x['group'], list)]) - set(constraint_groups.keys())) > 0:
            raise ValueError('cannot define group_constraints for groups that are not defined')
        if len(set([x['group'] for x in asset_constraints
                    if not isinstance(x['group'], list)]) - set(constraint_groups.keys())) > 0:
            raise ValueError('cannot define asset_constraints for groups that are not defined')

        # make sure constraints are not defined for assets that are not defined
        if assets is None:
            assets = []
            if constraint_groups:
                assets += [x for y in constraint_groups for x in constraint_groups[y]]
            if group_constraints:
                assets += [y for x in group_constraints for y in x['group'] if isinstance(x['group'], list)]
            if asset_constraints:
                assets += [y for x in asset_constraints for y in x['group'] if isinstance(x['group'], list)]
            assets = list(set(assets))
        if len(set([y for x in group_constraints for y in x['group']
                    if isinstance(x['group'], list)]) - set(assets)) > 0:
            raise ValueError('cannot define group_constraints for assets that are not defined')
        if len(set([y for x in asset_constraints for y in x['group']
                    if isinstance(x['group'], list)]) - set(assets)) > 0:
            raise ValueError('cannot define asset_constraints for assets that are not defined')

        # convert asset constraints to net constraints and add them to the group constraints
        temp_constraints = [dict(list(x.items()) + [('group', [y]), ('weights', [1.])])
                            for x in asset_constraints
                            for y in x['group']
                            if isinstance(x['group'], list)]
        group_constraints += temp_constraints
        temp_constraints = [dict(list(x.items()) + [('group', [y]), ('weights', [1.])])
                            for x in asset_constraints
                            for y in constraint_groups[x['group']]
                            if not isinstance(x['group'], list)]
        group_constraints += temp_constraints

        # check that bounds are all of known type
        recognized_constraint_types = ['net', 'gross', 'long', 'short', 'quadratic',
                                       'buys', 'sells', 'gross_turnover', 'net_turnover']
        if not all([x['type'] in recognized_constraint_types for x in group_constraints]):
            raise ValueError("bound_type has to be 'net', 'gross', 'long', 'short', 'quadratic'," +
                             " 'buys', 'sells', 'gross_turnover', or 'net_turnover'")

        # will multiply scaleable constraints by risk target / tuning risk target so any risk target changes
        # adapt the constraint sizes natively --> THIS IS THE DEFAULT BEHAVIOR
        constraint_multiplier = 1.
        if risk_target and tuning_risk_target:
            constraint_multiplier = risk_target / tuning_risk_target

        # initialize constraint structure
        constraint_dict = {}
        constraint_count = {}
        constraint_time_indices = {}
        for bound_type in recognized_constraint_types:
            m = len([x for x in group_constraints if (x['type'] == bound_type)])

            time_indices = []
            time_indices += [x['weights'].index for x in group_constraints
                             if ((x['type'] == bound_type) and
                                 ('weights' in x) and
                                 (not isinstance(x['weights'], (list, np.array))) and
                                 isinstance(x['weights'].index, pd.DatetimeIndex))]
            time_indices += [x['lower_bound'].index for x in group_constraints
                             if ((x['type'] == bound_type) and
                                 ('lower_bound' in x) and
                                 (not isinstance(x['lower_bound'], (float, int))) and
                                 isinstance(x['lower_bound'].index, pd.DatetimeIndex))]
            time_indices += [x['upper_bound'].index for x in group_constraints
                             if ((x['type'] == bound_type) and
                                 ('upper_bound' in x) and
                                 (not isinstance(x['upper_bound'], (float, int))) and
                                 isinstance(x['upper_bound'].index, pd.DatetimeIndex))]
            time_indices += [x['bound'].index for x in group_constraints
                             if ((x['type'] == bound_type) and
                                 ('bound' in x) and
                                 (not isinstance(x['bound'], (float, int))) and
                                 isinstance(x['bound'].index, pd.DatetimeIndex))]
            time_axis = None
            if len(time_indices) > 0:
                time_axis = time_indices[0]
                for i in range(1, len(time_indices)):
                    time_axis = time_axis.union(time_indices[i])
            constraint_time_indices[bound_type] = time_axis

            constraint_dict[bound_type] = {}
            if time_axis is not None:
                constraint_dict[bound_type]['weights'] = Panel3D(items=time_axis,
                                                                  major_axis=range(m),
                                                                  minor_axis=assets,
                                                                  dtype=float)
                constraint_dict[bound_type]['lower_bounds'] = pd.DataFrame(index=time_axis,
                                                                           columns=range(m),
                                                                           dtype=float)
                constraint_dict[bound_type]['upper_bounds'] = pd.DataFrame(index=time_axis,
                                                                           columns=range(m),
                                                                           dtype=float)
            else:
                constraint_dict[bound_type]['weights'] = pd.DataFrame(index=range(m),
                                                                      columns=assets,
                                                                      dtype=float)
                constraint_dict[bound_type]['lower_bounds'] = pd.Series(index=range(m),
                                                                        dtype=float)
                constraint_dict[bound_type]['upper_bounds'] = pd.Series(index=range(m),
                                                                        dtype=float)
            constraint_count[bound_type] = 0

        # run through and process each constraint
        for constraint in group_constraints:
            if len(set(constraint_groups[constraint['group']]) - set(assets)) > 0:
                raise ValueError('cannot define constraint groups which contain non-traded assets')

            constraint_group = constraint['group']
            if not isinstance(constraint_group, list):
                constraint_group = constraint_groups[constraint_group]
            constraint_weights = [1.]*len(constraint_group)
            if 'weights' in constraint:
                constraint_weights = constraint['weights']
            if len(constraint_weights) != len(constraint_group):
                raise ValueError('weights must be a list of the same length as the group specified')

            if ('bound' in constraint) and (('lower_bound' in constraint) or ('upper_bound' in constraint)):
                raise ValueError('cannot use both bound and either lower_bound or upper_bound in a constraint')

            if 'upper_bound' in constraint:
                upper_bound = constraint['upper_bound']
            else:
                upper_bound = constraint['bound']
            if (isinstance(upper_bound, (float, int)) and upper_bound < 0) or any(pd.Series(upper_bound) < 0):
                raise ValueError('upper bounds must be positive numbers')

            lower_bound = None
            temp_multiplier = constraint_multiplier
            if constraint['type'] in ['gross', 'long', 'short', 'buys', 'sells', 'gross_turnover', 'quadratic']:
                if 'lower_bound' in constraint:
                    raise ValueError('cannot specify lower bounds on gross style or quadratic constraints')
                lower_bound = None

                if constraint['type'] == 'quadratic':
                    temp_multiplier = constraint_multiplier**2.

            elif constraint['type'] in ['net', 'net_turnover']:
                if 'lower_bound' in constraint:
                    lower_bound = constraint['lower_bound']
                elif 'bound' in constraint:
                    lower_bound = -constraint['bound']
                if (isinstance(lower_bound, (float, int)) and lower_bound > 0) or any(pd.Series(lower_bound) > 0):
                    raise ValueError('lower bounds must be negative numbers')

            if not (('scale' in constraint) and (not constraint['scale'])):
                if upper_bound is not None:
                    upper_bound *= temp_multiplier
                if lower_bound is not None:
                    lower_bound *= temp_multiplier

            if constraint_time_indices[constraint['type']] is not None:
                if not isinstance(upper_bound, (pd.Series, pd.DataFrame)):
                    upper_bound = pd.Series(upper_bound, index=constraint_time_indices[constraint['type']])
                if not isinstance(lower_bound, (pd.Series, pd.DataFrame)):
                    lower_bound = pd.Series(lower_bound, index=constraint_time_indices[constraint['type']])
                if not isinstance(constraint_weights, pd.DataFrame):
                    constraint_weights = pd.Series(constraint_weights, index=constraint_group, dtype=float)
                    constraint_weights = pd.DataFrame(index=constraint_time_indices[constraint['type']],
                                                      columns=constraint_group,
                                                      dtype=float).apply(lambda x: constraint_weights, axis=1)
                constraint_dict[constraint['type']]['upper_bounds'].loc[:, constraint_count[constraint['type']]] = upper_bound
                constraint_dict[constraint['type']]['lower_bounds'].loc[:, constraint_count[constraint['type']]] = lower_bound
                constraint_dict[constraint['type']]['weights'].loc[:, constraint_count[constraint['type']],
                                                                   constraint_group] = constraint_weights.T
            else:
                constraint_dict[constraint['type']]['upper_bounds'].loc[constraint_count[constraint['type']]] = upper_bound
                constraint_dict[constraint['type']]['lower_bounds'].loc[constraint_count[constraint['type']]] = lower_bound
                constraint_dict[constraint['type']]['weights'].loc[constraint_count[constraint['type']],
                                                                   constraint_group] = constraint_weights
            constraint_count[constraint['type']] += 1

        for bound_type in recognized_constraint_types:
            constraint_dict[bound_type]['weights'] = constraint_dict[bound_type]['weights'].fillna(0.)

        constraint_dict = dict([(x, constraint_dict[x])
                                for x in constraint_dict
                                if not constraint_dict[x]['weights'].empty])

        # return the structures
        return constraint_dict

    def mean_variance(self,
                      alphas,
                      covariances,
                      initial_holdings=None,
                      risk_aversion=1.0,
                      transaction_cost_aversion=1.0,
                      transaction_costs=None,
                      market_impact_multipliers=None,
                      market_impact_exponent=0.0,
                      constraint_dict=None,
                      constraint_covariances=None):
        """
        Solve a time series of mean variance optimizations with transaction costs and constraints

        Parameters
        ----------
        alphas : DataFrame
            alphas, i.e, expected returns for assets. axes should be [time, asset]
        covariances : Panel
            asset covariance matrices over time. axes should be [time, asset, asset]
        initial_holdings : Series, optional
            vector of initial holdings. axis should be [asset] (defaults to zero positions for all assets)
        risk_aversion : float, optional
            risk aversion, used to control portfolio's ex-post risk (defaults to 1.0)

        transaction_cost_aversion : float, optional
            transaction cost aversion, used to control aversion to tcosts in the optimization (defaults to 1.0)
        transaction_costs : float, Series, or DataFrame, optional
            transaction costs per unit of change in asset weights. defaults to None. This can either be a float
            (same tcosts for all assets), a pandas Series where each asset can have a different tcost,
             or a pandas DataFrame where each asset can have a different tcost at different points in time.
        market_impact_multipliers : float, Series, or DataFrame, optional
            multipliers on non-linear term on trade sizes, used to control aversion to trade sizes above and beyond
            the linear aversion controlled by the transaction_cost parameters. defaults to 0.0. This can either be a
            float (same multiplier for all assets), a pandas Series where each asset can have a different multiplier,
             or a pandas DataFrame where each asset can have a different multiplier at different points in time.
        market_impact_exponent : float, optional, must be 0.0, 0.5, or 1.0
            exponent for non-linear transaction cost term on gross trade sizes. can only be 0.0, 0.5, or 1.0.
            defaults to 0.0.
           ######  The form for transaction costs in the objective function is assumed to be: ######
                                    tca * (tc + mim * |trade_sizes| ^ mie) * |trade_sizes|
                    where tca = transaction_cost_aversion
                          tc = transaction_costs
                          mim = market_impact_multipliers
                          mie = market_impact_exponent (can only be 0.0, 0.5, or 1.0 - defaults to 0.0)

        constraint_dict : dictionary of dictionaries
            dictionary of dictionaries of constraints with primary key being the type of constraint to impose and
            secondary keys being weights, lower_bounds, and upper_bounds. for example, the constraint_dict takes
            the following form:
                'net' :
                    'upper_bounds' : None, list, array, Series, or DataFrame
                        upper bounds for net constraints. if not DataFrame, length must match the length of the
                        first (if DataFrame) or second (if Panel) axis of weights. if DataFrame, the time axis
                        must match any time axis of weights. if DataFrame, this is used for setting different bounds
                        for different points in time.
                    'lower_bounds' : None, list, array, Series, or DataFrame
                        lower bounds for net constraints. if not DataFrame, length must match the length of the
                        first (if DataFrame) or second (if Panel) axis of weights. if DataFrame, the time axis
                        must match any time axis of weights. if DataFrame, this is used for setting different bounds
                        for different points in time.
                    'weights' : None, DataFrame, or Panel
                        weights to apply before imposing the net constraint, axes are [constraint, asset] if
                        DataFrame, or [time, constraint, asset] if Panel. I.e. different weights can be set for
                        different points in time. can use all 1s if "no weight" is wanted for a given constraint
                        on all assets, 0s and 1s if "no weight" is wanted for a given constraint on a subset or
                        single asset, or arbitrary floats (positive or negative) if arbitrary portfolios or spreads
                        need to be constrained. if Panel, time axis must match time axis of covariances.
                'gross' :
                    'upper_bounds' : None, list, array, Series, or DataFrame
                        upper bounds for gross constraints...
                etc...
            The different bound types that can be specified are:
                net: specify a constraint on the net positions
                gross: specify a constraint on the gross positions (upper bound only)
                long: specify a constraint on just the long positions (upper bound only)
                short: specify a constraint on just the short positions (upper bound only)
                net_turnover: specify a constraint on the net turnover
                gross_turnover: specify a constraint on the gross turnover (upper bound only)
                buys: specify a constraint on just the buys (upper bound only)
                sells: specify a constraint on just the sells (upper bound only)
                quadratic: specify a constraint on the variance of a (sub-)portfolio (upper bound only)

        constraint_covariances : Panel, optional
            asset covariance matrices over time. axes should be [time, asset, asset]. defaults to covariances passed
            in above. allows a user to use one covariance for the objective function, and a separate covariance for
            constraints, so for example, one can use a shrunk covariance in the objective, but a full covariance in
            constraints, or covariances in the objective and constraints that differ in terms of their half-lives

        Returns
        -------
        weights : DataFrame
            time series of optimal holdings produced by the optimizer, axes are [time, asset]
        """

        # initialize initial holdings as necessary
        if initial_holdings is None:
            initial_holdings = pd.Series(0.0, index=alphas.columns)

        # allow transaction_costs to be specified in a number of different ways
        if transaction_costs is None:
            transaction_costs = pd.DataFrame(0.0, index=alphas.index, columns=alphas.columns)
        elif isinstance(transaction_costs, (int, float)):
            if np.isnan(transaction_costs):
                transaction_costs = 0
            transaction_costs = pd.DataFrame(float(transaction_costs), index=alphas.index, columns=alphas.columns)
        elif isinstance(transaction_costs, list):
            if len(transaction_costs) != len(alphas.columns):
                raise ValueError('length of transaction_costs (%d) is not equal to number of assets in alphas (%d)' %
                                 (len(transaction_costs), len(alphas.columns)))
            else:
                new_transaction_costs = pd.DataFrame(np.nan, index=alphas.index, columns=alphas.columns)
                row = pd.Series(transaction_costs, index=alphas.columns)
                new_transaction_costs.iloc[0, :] = row
                new_transaction_costs = new_transaction_costs.ffill()
                new_transaction_costs = new_transaction_costs.astype(float)
                transaction_costs = new_transaction_costs
        elif isinstance(transaction_costs, pd.Series):
            if set(transaction_costs.index) != set(alphas.columns):
                raise ValueError('transaction_costs and alphas must have the same set of assets')
            new_transaction_costs = pd.DataFrame(np.nan, index=alphas.index, columns=alphas.columns)
            new_transaction_costs.iloc[0, :] = transaction_costs.reindex(index=alphas.columns)
            new_transaction_costs = new_transaction_costs.ffill()
            new_transaction_costs = new_transaction_costs.astype(float)
            transaction_costs = new_transaction_costs
        elif isinstance(transaction_costs, pd.DataFrame):
            if not transaction_costs.index.equals(alphas.index):
                raise ValueError('transaction_costs and alphas must have the same index')
            if set(transaction_costs.columns) != set(alphas.columns):
                raise ValueError('transaction_costs and alphas must have the same set of assets')
            transaction_costs = transaction_costs.reindex(columns=alphas.columns)
        else:
            raise TypeError('transaction_costs must be an int, float, list, Series, or DataFrame')

        # allow market_impact_multipliers to be specified in a number of different ways
        if market_impact_multipliers is None:
            market_impact_multipliers = pd.DataFrame(0.0, index=alphas.index, columns=alphas.columns)
        elif isinstance(market_impact_multipliers, (int, float)):
            if np.isnan(market_impact_multipliers):
                market_impact_multipliers = 0
            market_impact_multipliers = pd.DataFrame(float(market_impact_multipliers),
                                                     index=alphas.index, columns=alphas.columns)
        elif isinstance(market_impact_multipliers, list):
            if len(market_impact_multipliers) != len(alphas.columns):
                raise ValueError('length of market_impact_multipliers (%d) ' % len(market_impact_multipliers) +
                                 'is not equal to number of assets in alphas (%d)' % len(alphas.columns))
            else:
                new_market_impact_multipliers = pd.DataFrame(np.nan, index=alphas.index, columns=alphas.columns)
                row = pd.Series(market_impact_multipliers, index=alphas.columns)
                new_market_impact_multipliers.iloc[0, :] = row
                new_market_impact_multipliers = new_market_impact_multipliers.ffill()
                new_market_impact_multipliers = new_market_impact_multipliers.astype(float)
                market_impact_multipliers = new_market_impact_multipliers
        elif isinstance(market_impact_multipliers, pd.Series):
            if set(market_impact_multipliers.index) != set(alphas.columns):
                raise ValueError('market_impact_multipliers and alphas must have the same set of assets')
            new_market_impact_multipliers = pd.DataFrame(np.nan, index=alphas.index, columns=alphas.columns)
            new_market_impact_multipliers.iloc[0, :] = market_impact_multipliers.reindex(index=alphas.columns)
            new_market_impact_multipliers = new_market_impact_multipliers.ffill()
            new_market_impact_multipliers = new_market_impact_multipliers.astype(float)
            market_impact_multipliers = new_market_impact_multipliers
        elif isinstance(market_impact_multipliers, pd.DataFrame):
            if not market_impact_multipliers.index.equals(alphas.index):
                raise ValueError('market_impact_multipliers and alphas must have the same index')
            if set(market_impact_multipliers.columns) != set(alphas.columns):
                raise ValueError('market_impact_multipliers and alphas must have the same set of assets')
            market_impact_multipliers = market_impact_multipliers.reindex(columns=alphas.columns)
        else:
            raise TypeError('market_impact_multipliers must be an int, float, list, Series, or DataFrame')

        # default is no constraints
        if constraint_dict is None:
            constraint_dict = {}

        # set the default covariance to use for quadratic constraints to the covariance used for the objective, but
        # not that this does not have to be the case. i.e. you may want to use a shrunk / modeled covariance for
        # the objective, but an empirical covariance for constraints, or use covariances derived with different time
        # scales for example
        if constraint_covariances is None:
            constraint_covariances = covariances.copy()

        for bound_type in constraint_dict:
            bound_weights = constraint_dict[bound_type]['weights']
            upper_bounds = constraint_dict[bound_type]['upper_bounds']
            lower_bounds = constraint_dict[bound_type]['lower_bounds']

            constraint_count = 0
            if isinstance(bound_weights, Panel3D):
                constraint_count = bound_weights.shape[0]
                if set(bound_weights.minor_axis) != set(covariances.minor_axis):
                    raise ValueError("%s['weights'].minor_axis: %s should have " % (bound_type,
                                                                                    list(bound_weights.minor_axis)) +
                                     "the same set of assets in covariances.minor_axis: %s" %
                                     list(covariances.minor_axis))
                if not isinstance(bound_weights.items, pd.DatetimeIndex):
                    raise ValueError("%s['weights'].items is not of type pd.DatetimeIndex." % bound_type +
                                     " If %s['weights'] is a Panel its axes should be ordered as " % bound_type +
                                     "[time, constraint name, asset] (constraint name can be factor name for instance)")
            elif isinstance(bound_weights, pd.DataFrame):
                constraint_count = bound_weights.shape[0]
                if set(bound_weights.columns) != set(covariances.minor_axis):
                    raise ValueError("%s['weights'].columns: %s should have " % (bound_type,
                                                                                 list(bound_weights.columns)) +
                                     "the same set of assets in covariances.minor_axis: %s" %
                                     list(covariances.minor_axis))

            if isinstance(upper_bounds, pd.DataFrame):
                upper_bound_count = upper_bounds.shape[1]
            else:
                upper_bound_count = len(upper_bounds)
            if constraint_count and (upper_bound_count != constraint_count):
                raise ValueError("%s['upper_bounds']: should have " % bound_type +
                                 "the same length as the constraint axis of weights")

            if isinstance(lower_bounds, pd.DataFrame):
                lower_bound_count = lower_bounds.shape[1]
            else:
                lower_bound_count = len(lower_bounds)
            if constraint_count and (lower_bound_count != constraint_count):
                raise ValueError("%s['lower_bounds']: should have " % bound_type +
                                 "the same length as the constraint axis of weights")

        # get covariance for each day
        covariance_index = covariances.items
        dropped_covariance_index = covariances.dropna(how='all').items
        dropped_constraint_covariance_index = constraint_covariances.dropna(how='all').items
        dropped_alpha_index = alphas.dropna(how='all').index
        index = dropped_covariance_index.intersection(dropped_alpha_index)
        index = dropped_constraint_covariance_index.intersection(index)

        # fill forward the bounds to match the index as well
        for bound_type in constraint_dict:
            if (isinstance(constraint_dict[bound_type]['weights'], Panel3D) or
                    (isinstance(constraint_dict[bound_type]['weights'], pd.DataFrame) and
                         isinstance(constraint_dict[bound_type]['weights'].index, pd.DatetimeIndex))):
                constraint_dict[bound_type]['weights'] = \
                    constraint_dict[bound_type]['weights'].reindex(index).fillna(method='ffill', axis=0)

            if (isinstance(constraint_dict[bound_type]['upper_bounds'], pd.DataFrame) and
                    isinstance(constraint_dict[bound_type]['upper_bounds'].index, pd.DatetimeIndex)):
                constraint_dict[bound_type]['upper_bounds'] = \
                    constraint_dict[bound_type]['upper_bounds'].reindex(index).fillna(method='ffill', axis=0)

            if (isinstance(constraint_dict[bound_type]['lower_bounds'], pd.DataFrame) and
                    isinstance(constraint_dict[bound_type]['lower_bounds'].index, pd.DatetimeIndex)):
                constraint_dict[bound_type]['lower_bounds'] = \
                    constraint_dict[bound_type]['lower_bounds'].reindex(index).fillna(method='ffill', axis=0)

        weights = self._process_one_period_dispatch(index, alphas, covariances, initial_holdings, risk_aversion,
                                                    transaction_cost_aversion, transaction_costs,
                                                    market_impact_multipliers, market_impact_exponent,
                                                    constraint_dict, constraint_covariances)

        weights = pd.DataFrame(weights, columns=covariance_index, dtype=float).T

        return weights

    def _process_one_period_dispatch(self, index, alphas, covariances, initial_holdings, risk_aversion,
                                     transaction_cost_aversion, transaction_costs, market_impact_multipliers,
                                     market_impact_exponent, constraint_dict, constraint_covariances=None):
        """
        helper function to wrap the single period mean variance optimization code in a for loop
        """

        previous_holdings = initial_holdings.copy()
        holdings = {}

        # set the default covariance to use for quadratic constraints to the covariance used for the objective, but
        # not that this does not have to be the case. i.e. you may want to use a shrunk / modeled covariance for
        # the objective, but an empirical covariance for constraints, or use covariances derived with different time
        # scales for example
        if constraint_covariances is None:
            constraint_covariances = covariances.copy()

        for d in index:
            alpha = alphas.loc[d]
            covariance = covariances.loc[d]
            transaction_cost = transaction_costs.loc[d]
            market_impact_multiplier = market_impact_multipliers.loc[d]
            constraint_covariance = constraint_covariances.loc[d]

            constraints_one_period = {}
            for bound_type in constraint_dict:
                bound_weights = constraint_dict[bound_type]['weights']

                constraints_one_period[bound_type] = {}
                upper_bounds = constraint_dict[bound_type]['upper_bounds']
                lower_bounds = constraint_dict[bound_type]['lower_bounds']

                if isinstance(bound_weights, Panel3D):
                    if d in bound_weights.items:
                        constraints_one_period[bound_type]['weights'] = bound_weights.loc[d]
                    else:
                        constraints_one_period[bound_type]['weights'] = None
                elif isinstance(bound_weights, pd.DataFrame) and isinstance(bound_weights.index, pd.DatetimeIndex):
                    # if there is only one row of bound weights but it is time varying, this lets
                    # the user pass in a DataFrame instead of having to construct a Panel
                    if d in bound_weights.index:
                        constraints_one_period[bound_type]['weights'] = bound_weights.loc[d]
                    else:
                        constraints_one_period[bound_type]['weights'] = None
                else:
                    constraints_one_period[bound_type]['weights'] = bound_weights

                if isinstance(upper_bounds, pd.DataFrame):
                    if d in upper_bounds.index:
                        constraints_one_period[bound_type]['upper_bounds'] = upper_bounds.loc[d]
                    else:
                        constraints_one_period[bound_type]['upper_bounds'] = None
                else:
                    constraints_one_period[bound_type]['upper_bounds'] = upper_bounds

                if isinstance(lower_bounds, pd.DataFrame):
                    if d in lower_bounds.index:
                        constraints_one_period[bound_type]['lower_bounds'] = lower_bounds.loc[d]
                    else:
                        constraints_one_period[bound_type]['lower_bounds'] = None
                else:
                    constraints_one_period[bound_type]['lower_bounds'] = lower_bounds

            optimal_holdings = self.mean_variance_one_period(alpha,
                                                             covariance,
                                                             initial_holdings=previous_holdings,
                                                             risk_aversion=risk_aversion,
                                                             transaction_cost_aversion=transaction_cost_aversion,
                                                             transaction_costs=transaction_cost,
                                                             market_impact_multipliers=market_impact_multiplier,
                                                             market_impact_exponent=market_impact_exponent,
                                                             constraint_dict=constraints_one_period,
                                                             constraint_covariance=constraint_covariance)
            holdings[d] = optimal_holdings
            previous_holdings = optimal_holdings

        return holdings

    def mean_variance_one_period(self,
                                 alpha,
                                 covariance,
                                 initial_holdings=None,
                                 risk_aversion=1.0,
                                 transaction_cost_aversion=1.0,
                                 transaction_costs=None,
                                 market_impact_multipliers=None,
                                 market_impact_exponent=0.0,
                                 constraint_dict=None,
                                 constraint_covariance=None):
        """
        Solve a time series of mean variance optimizations with transaction costs and constraints

        Parameters
        ----------
        alphas : DataFrame
            alphas, i.e, expected returns for assets. axes should be [time, asset]
        covariance : DataFrame
            asset covariance matrix. axes should be [asset, asset]
        initial_holdings : Series, optional
            vector of initial holdings. axis should be [asset] (defaults to zero positions for all assets)
        risk_aversion : float, optional
            risk aversion, used to control portfolio's ex-post risk (defaults to 1.0)

        transaction_cost_aversion : float, optional
            transaction cost aversion, used to control aversion to tcosts in the optimization (defaults to 1.0)
        transaction_costs : float or Series, optional
            transaction costs per unit of change in asset weights. defaults to None. This can either be a float
            (same tcosts for all assets), a pandas Series where each asset can have a different tcost.
        market_impact_multipliers : float or Series, optional
            multipliers on non-linear term on trade sizes, used to control aversion to trade sizes above and beyond
            the linear aversion controlled by the transaction_cost parameters. defaults to 0.0. This can either be a
            float (same multiplier for all assets), a pandas Series where each asset can have a different multiplier.
        market_impact_exponent : float, optional
            exponent for non-linear transaction cost term on gross trade sizes. can only be 0.0, 0.5, or 1.0.
            defaults to 0.0.
        ###########  The form for transaction costs in the objective function is assumed to be: ############
                                    tca * (tc + mim * |trade_sizes| ^ mie) * |trade_sizes|
                    where tca = transaction_cost_aversion
                          tc = transaction_costs
                          mim = market_impact_multipliers
                          mie = market_impact_exponent (can only be 0.0, 0.5, or 1.0 - defaults to 0.0)

        constraint_dict : dictionary of dictionaries
            dictionary of dictionaries of constraints with primary key being the type of constraint to impose and
            secondary keys being weights, lower_bounds, and upper_bounds. for example, the constraint_dict takes
            the following form:
                'net' :
                    'upper_bounds' : None, list, array, or Series
                        upper bounds for net constraints. length must match the length of the first axis of weights.
                    'lower_bounds' : None, list, array, or Series
                        lower bounds for net constraints. length must match the length of the first axis of weights.
                    'weights' : None or DataFrame (possibly one row long)
                        weights to apply before imposing the net constraint, axes are [constraint, asset] can use
                        all 1s if "no weight" is wanted for a given constraint on all assets, 0s and 1s if
                        "no weight" is wanted for a given constraint on a subset or single asset, or arbitrary
                        floats (positive or negative) if arbitrary portfolios or spreads need to be constrained.
                'gross' :
                    'upper_bounds' : None, list, array, or Series
                        upper bounds for gross constraints...
                etc...
            The different bound types that can be specified are:
                net: specify a constraint on the net positions
                gross: specify a constraint on the gross positions (upper bound only)
                long: specify a constraint on just the long positions (upper bound only)
                short: specify a constraint on just the short positions (upper bound only)
                net_turnover: specify a constraint on the net turnover
                gross_turnover: specify a constraint on the gross turnover (upper bound only)
                buys: specify a constraint on just the buys (upper bound only)
                sells: specify a constraint on just the sells (upper bound only)
                quadratic: specify a constraint on the variance of a (sub-)portfolio (upper bound only)

        constraint_covariances : DataFrame, optional
            asset covariance matrix. axes should be [asset, asset]. defaults to covariances passed
            in above. allows a user to use one covariance for the objective function, and a separate covariance for
            constraints, so for example, one can use a shrunk covariance in the objective, but a full covariance in
            constraints, or covariances in the objective and constraints that differ in terms of their half-lives

        Returns
        -------
        weights : DataFrame
            time series of optimal holdings produced by the optimizer, axes are [time, asset]
        """

        if not isinstance(alpha, pd.Series):
            raise TypeError('alpha needs to be a Series')
        alpha = alpha.astype(float)

        # active assets are ones that have non-nan covariance and non-nan alpha values
        assets = covariance.index
        covariance = covariance.dropna(axis=0, how='all').dropna(axis=1, how='all')
        # check that the covariance indices are equal
        # pandas 0.x: Index.__and__ was set intersection. Modern pandas makes it an elementwise
        # logical AND, which raises on string labels rather than silently returning something odd.
        active_assets = covariance.index.intersection(covariance.columns).intersection(alpha.dropna().index)
        if len(active_assets) == 0:
            if not covariance.index.equals(covariance.columns):
                raise ValueError('Cov has unequal index and columns. Consider checking for dtype mismatch')
            else:
                raise ValueError('Alphas and covariance have no active assets in common')
        covariance = pd.DataFrame(covariance, index=active_assets, columns=active_assets)
        covariance_array = np.array(covariance)

        # set the default covariance to use for quadratic constraints to the covariance used for the objective, but
        # not that this does not have to be the case. i.e. you may want to use a shrunk / modeled covariance for
        # the objective, but an empirical covariance for constraints, or use covariances derived with different time
        # scales for example
        if constraint_covariance is None:
            constraint_covariance = covariance.copy()
        constraint_covariance = pd.DataFrame(constraint_covariance, index=active_assets, columns=active_assets)

        if transaction_costs is None:
            transaction_costs = pd.Series(0.0, index=active_assets)
        elif isinstance(transaction_costs, (int, float)):
            transaction_costs = pd.Series(float(transaction_costs), index=active_assets)
        elif isinstance(transaction_costs, (list, pd.Series)):
            transaction_costs = pd.Series(transaction_costs, index=active_assets)
        else:
            raise TypeError('transaction_costs parameter should either be None, a float/int, or a Series')

        if market_impact_multipliers is None:
            market_impact_multipliers = pd.Series(0.0, index=active_assets)
        elif isinstance(market_impact_multipliers, (int, float)):
            market_impact_multipliers = pd.Series(float(market_impact_multipliers), index=active_assets)
        elif isinstance(market_impact_multipliers, (list, pd.Series)):
            market_impact_multipliers = pd.Series(market_impact_multipliers, index=active_assets)
        else:
            raise TypeError('market_impact_multipliers parameter should either be None, a float/int, or a Series')

        if market_impact_exponent not in [0.0, 0.5, 1.0]:
            raise ValueError('market_impact_exponent can only be 0.0. 0.5, or 1.0')

        if initial_holdings is None:
            initial_holdings = pd.Series(np.nan, index=active_assets)

        x_init = np.array(initial_holdings.reindex(active_assets).fillna(0.0))
        alpha_array = np.array(alpha.reindex(active_assets))

        n = len(x_init)
        if n < 2:
            return pd.Series(np.nan, index=assets)

        # k1 is the linear transaction_costs, adjusted by transaction_cost aversion
        k1 = np.array(transaction_costs) * transaction_cost_aversion

        # k2 is the higher order transaction_cost coefficients
        k2 = np.array(market_impact_multipliers) * transaction_cost_aversion

        # Massage everything into the cvxopt qp function that solves the quadratic program
        #
        # minimize   (1/2) * x' * P * x + q'* x
        # subject to   G * x <= h
        #              A * x = b

        # figure out what the best dimension multiplier is: 1, 2, or 4
        if (transaction_costs == 0).all() and (market_impact_multipliers == 0).all():
            x_init = np.zeros(len(x_init))
            dimension_multiplier = 1
        else:
            # if transaction_cost is non-zero, we need to double dimension
            dimension_multiplier = 2
        # if gross bounds on trades are specified, dimension needs to double
        if (~pd.isnull([constraint_dict[x]['upper_bounds']
                        for x in constraint_dict
                        if x in ['buys', 'sells', 'gross_turnover']])).any():
            dimension_multiplier = 2
        # if gross bounds on positions are specified, dimension needs to be 4
        if (~pd.isnull([constraint_dict[x]['upper_bounds']
                        for x in constraint_dict
                        if x in ['gross', 'long', 'short']])).any():
            dimension_multiplier = 4

        # the optimization is structured around trades not positions, i.e. it's structured around
        # x_trades (= x_final - x_init)

        if dimension_multiplier == 1:
            P, q, G, h = self.__setup_problem_arrays_d1(alpha_array, covariance_array, x_init, risk_aversion)

        elif dimension_multiplier == 2:
            P, q, G, h = self.__setup_problem_arrays_d2(alpha_array, covariance_array, x_init, risk_aversion, k1)

        elif dimension_multiplier == 4:
            P, q, G, h = self.__setup_problem_arrays_d4(alpha_array, covariance_array, x_init, risk_aversion, k1)

        else:
            raise ValueError('dimension_multiplier must be 1, 2, or 4')

        # process portfolio constraints
        A = [None]*len(G)  # array of symmetric matrices for quadratic inequality constraints
        for bound_type in constraint_dict:
            upper_bounds = None
            if 'upper_bounds' in constraint_dict[bound_type]:
                upper_bounds = constraint_dict[bound_type]['upper_bounds']
            lower_bounds = None
            if 'lower_bounds' in constraint_dict[bound_type]:
                lower_bounds = constraint_dict[bound_type]['lower_bounds']
            bound_weights = None
            if 'weights' in constraint_dict[bound_type]:
                bound_weights = constraint_dict[bound_type]['weights']

            if (bound_type in ['gross', 'long', 'short', 'buys', 'sells', 'gross_turnover', 'quadratic']) \
                    and (not ((lower_bounds is None) or all(pd.isnull(lower_bounds)))):
                raise ValueError('cannot specify a lower bound for %s constraint type' % bound_type)
            if (upper_bounds is not None) and any([x < 0 for x in upper_bounds]):
                raise ValueError('upper bounds must be positive numbers')
            if (lower_bounds is not None) and any([x > 0 for x in lower_bounds]):
                raise ValueError('lower bounds must be negative numbers')

            A, G, h = self.__process_portfolio_constraints(A, G, h,
                                                           upper_bounds, lower_bounds, bound_weights,
                                                           active_assets, x_init, constraint_covariance,
                                                           alpha.index, dimension_multiplier, bound_type=bound_type)

        # add the non-linear market impact term
        B, F, k = [], [], []
        if (dimension_multiplier in [2, 4]) and (not (k2 == 0).all()):
            if market_impact_exponent == 1.:
                P += np.diag(np.tile(k2, dimension_multiplier))
            elif market_impact_exponent == 0.5:
                msg = 'market_impact_exponent = 0.5 has not yet been implemented / debugged.'
                msg += ' can use market_impact_exponent = 1.0 if non-linear (quadratic) impact terms are desired'
                raise ValueError(msg)
                P, q, A, G, h, \
                B, F, k = self.__extend_problem_with_square_root_market_impact(P, q, A, G, h,
                                                                               k2, dimension_multiplier)

        # solve the problem
        if (pd.isnull(A)).all() and (pd.isnull(B)).all():
            # this problem has no explicit or implicit quadratic constraints. solve with qp directly.
            # suppress output from qp solver
            cvxopt.solvers.options['show_progress'] = False
            result = cvxopt.solvers.qp(P=cvxopt.matrix(P), q=cvxopt.matrix(q), G=cvxopt.matrix(G), h=cvxopt.matrix(h))

        else:
            # this problem has explicit or implicit quadratic constraints. must recast since cvxopt does not have
            # any direct methods for solving qcqp problems

            # #######################################################################################################
            # ################     RECAST PROBLEM FROM A QP TO AN SDP TO HANDLE QUADRATIC CONSTRAINTS     ###########
            # TRANSLATE FROM:
            # minimize   (1/2) * x' * P * x + q'* x
            # subject to   G * x <= h
            #              A * x = b
            # TO:
            # minimize   (1/2) * x' * P * x + q'* x
            # subject to   x' * A * x + G * x + h <= 0
            #              x' * B * x + F * x + k = 0
            # #######################################################################################################
            # #######################################################################################################

            objective = {'P': P, 'q': q}
            inequality_constraints = {'A': A, 'G': G, 'h': -h}  # note spec difference on h
            equality_constraints = None
            if (~pd.isnull(B)).any():
                equality_constraints = {'A': B, 'G': F, 'h': -k}  # note spec difference on h

            result = self.solve_qcqp_via_sdp_recasting(objective, inequality_constraints, equality_constraints)

        # pull the holdings out of the optimizer response
        if result['status'] == 'optimal':
            x = np.nan
            if dimension_multiplier == 1:
                x = np.reshape(np.array(result['x']), (n,))

            elif dimension_multiplier == 2:
                x_buy = np.reshape(np.array(result['x'])[:n], (n,))
                x_sell = np.reshape(np.array(result['x'])[n:2*n], (n,))
                x = x_init + x_buy - x_sell

            elif dimension_multiplier == 4:
                x_buy_bar = np.reshape(np.array(result['x'])[:n], (n,))
                x_buy_hat = np.reshape(np.array(result['x'])[n:2*n], (n,))
                x_sell_bar = np.reshape(np.array(result['x'])[2*n:3*n], (n,))
                x_sell_hat = np.reshape(np.array(result['x'])[3*n:4*n], (n,))
                x = x_init + x_buy_bar + x_buy_hat - x_sell_bar - x_sell_hat

            optimal_holdings = pd.Series(x, index=active_assets).reindex(assets)

        else:
            optimal_holdings = pd.Series(np.nan, index=assets)

        return optimal_holdings

    def __setup_problem_arrays_d1(self, alpha, covariance, x_init, risk_aversion):
        """
        function to set up the arrays for the canonical optimization problem where we do not have to upcast the
        problem to a higher dimension
        """

        # get problem size
        n = len(x_init)

        # objective quadratic term
        P = 0.5 * risk_aversion * covariance

        # objective linear term
        q = -alpha

        # inequality constraints, Gx <= h
        G = np.empty((0, n))
        h = np.empty((0, ))

        return P, q, G, h

    def __setup_problem_arrays_d2(self, alpha, covariance, x_init, risk_aversion, k1):
        """
        function to set up the arrays for the canonical optimization problem where we have to upcast the
        problem to a higher dimension to separate out buy trades and sell trades
        """

        # get problem size
        n = len(x_init)

        # the groups are (in this order): x_buy, x_sell

        # objective quadratic term
        # expand covariance into [[covariance, -covariance],
        #                         [-covariance, covariance]]
        tmp = np.vstack((covariance, -covariance))
        big_covariance = np.hstack((tmp, -tmp))
        P = 0.5 * risk_aversion * big_covariance

        # objective linear term
        tmp2 = 0.5 * risk_aversion * 2 * covariance.dot(x_init)
        # this tmp2 term is needed due to the casting of this problem on trades as opposed to positions
        # when you expand out (x_0 + x)'P(x_0+x) = x_0'Px_0 + 2x'Px_0 + x'Px, the first term goes away since
        # it's a constant, the second term becomes linear, and the third stays the standard quadratic
        q = np.hstack((k1, k1)) + np.hstack((tmp2, -tmp2)) - np.hstack((alpha, -alpha))

        # inequality constraints, Gx <= h
        # both x_buy and x_sell are positive numbers
        G = -1. * np.eye(2*n)
        h = np.zeros(2*n)

        return P, q, G, h

    def __setup_problem_arrays_d4(self, alpha, covariance, x_init, risk_aversion, k1):
        """
        function to set up the arrays for the canonical optimization problem where we have to upcast the
        problem to a higher dimension to separate out buying back shorts, buying longs, selling longs, and
        selling shorts
        """

        # get problem size
        n = len(x_init)

        # the groups are (in this order): x_buy_short, x_buy_long, x_sell_long, x_sell_short

        # objective quadratic term
        # expand covariance into [[covariance, covariance, -covariance, -covariance],
        #                         [covariance, covariance, -covariance, -covariance],
        #                         [-covariance, -covariance, covariance, covariance]
        #                         [-covariance, -covariance, covariance, covariance]]
        tmp = np.hstack((covariance, covariance, -covariance, -covariance))
        P = 0.5 * risk_aversion * np.vstack((tmp, tmp, -tmp, -tmp))

        # objective linear term
        tmp2 = k1 + 0.5 * risk_aversion * 2. * covariance.dot(x_init) - alpha
        tmp3 = k1 - 0.5 * risk_aversion * 2. * covariance.dot(x_init) + alpha
        # these tmp2 and tmp3 terms are needed due to the casting of this problem on trades as opposed to positions
        # when you expand out (h_0 + t)'P(h_0+t) = h_0'Ph_0 + 2t'Ph_0 + t'Pt, the first term goes away since
        # it's a constant, the second term becomes linear, and the third stays the standard quadratic
        q = np.hstack((tmp2, tmp2, tmp3, tmp3))

        # inequality constraints Gx <= h
        G = -1. * np.eye(4*n)
        h = np.zeros(4*n)
        # add constraints for x_buy_short <= |x_init|, x_sell_long <= |x_init|
        zeros = np.zeros((n, n))
        tmp4 = np.hstack((np.eye(n), zeros, zeros, zeros))
        G = np.vstack((G, tmp4))
        h = np.hstack((h, -np.minimum(0., x_init)))  # abs(x_init)
        tmp5 = np.hstack((zeros, zeros, np.eye(n), zeros))
        G = np.vstack((G, tmp5))
        h = np.hstack((h, np.maximum(0., x_init)))  # abs(x_init)

        return P, q, G, h

    def __process_portfolio_constraints(self, A, G, h,
                                        upper_bounds, lower_bounds, bound_weights,
                                        active_assets, x_init,
                                        constraint_covariance, alpha_index,
                                        dimension_multiplier, bound_type='net'):
        """
        helper function to standardize input constraint structures so that adding the constraints themselves
        need not worry about data types, alignment, etc...
        """

        if bound_weights is None:
            # two cases when bound_weights is None:
            # 1. If upper_bounds/lower_bounds are None or lists, there's no portfolio constraints
            # 2. If upper_bounds/lower_bounds are floats, bound_weights are defaulted to all 1's
            multiple_upper = isinstance(upper_bounds, (list, pd.Series)) and len(upper_bounds) > 1
            multiple_lower = isinstance(lower_bounds, (list, pd.Series)) and len(lower_bounds) > 1
            if multiple_upper or multiple_lower:
                raise ValueError(bound_type + '_bound_weights is empty but have multiple long/short constraints')
            A, G, h = self.__add_weighted_portfolio_constraint(A, G, h, upper_bounds, lower_bounds, bound_weights,
                                                               active_assets, x_init,
                                                               constraint_covariance, dimension_multiplier,
                                                               bound_type=bound_type)
        elif isinstance(bound_weights, (list, pd.Series)):
            # one row of weights given as a list or Series
            if isinstance(bound_weights, list) and len(bound_weights) != len(alpha_index):
                raise ValueError(bound_type + '_bound_weights should have the same length as the number of assets')
            bound_weights = pd.Series(bound_weights, index=alpha_index)
            A, G, h = self.__add_weighted_portfolio_constraint(A, G, h, upper_bounds, lower_bounds, bound_weights,
                                                               active_assets, x_init,
                                                               constraint_covariance, dimension_multiplier,
                                                               bound_type=bound_type)
        elif isinstance(bound_weights, pd.DataFrame):
            # ensure that bound weights covers all the assets
            bound_weights = pd.DataFrame(bound_weights, columns=alpha_index).fillna(0.)

            # if multiple rows of weights given as a DataFrame,
            # upper and lower bounds have to be lists of the same size as number of rows
            num_rows = len(bound_weights.index)

            # if not specified, means no bound on that side for all rows
            if upper_bounds is None:
                upper_bounds = [np.nan] * num_rows
            if lower_bounds is None:
                lower_bounds = [np.nan] * num_rows

            # check data types
            if not isinstance(upper_bounds, (list, pd.Series)):
                raise TypeError("%s constraint upper_bounds needs to be a list of floats " % bound_type +
                                "or a Series when weights is a DataFrame")
            if not isinstance(lower_bounds, (list, pd.Series)):
                raise TypeError("%s constraint lower_bounds needs to be a list of floats " % bound_type +
                                "or a Series when weights is a DataFrame")

            # now check size of lists
            if num_rows != len(upper_bounds):
                msg = "Length of %s constraint upper_bounds (%d) not equal number of rows (%d) in weights DataFrame." \
                      % (bound_type, len(upper_bounds), num_rows)
                msg += " Set bound value to None or NaN for any one-sided constraint"
                raise ValueError(msg)
            if num_rows != len(lower_bounds):
                msg = "Length of %s constraint lower_bounds (%d) not equal number of rows (%d) in weights DataFrame." \
                      % (bound_type, len(lower_bounds), num_rows)
                msg += " Set bound value to None or NaN for any one-sided constraint"
                raise ValueError(msg)

            A, G, h = self.__add_weighted_portfolio_constraint(A, G, h, upper_bounds, lower_bounds, bound_weights,
                                                               active_assets, x_init,
                                                               constraint_covariance, dimension_multiplier,
                                                               bound_type=bound_type)
        else:
            raise TypeError('%s constraint weights should be either a list, Series or DataFrame' % bound_type)

        return A, G, h

    def __add_weighted_portfolio_constraint(self, A, G, h,
                                            upper_bounds, lower_bounds, bound_weights,
                                            active_assets, x_init,  constraint_covariance,
                                            dimension_multiplier, bound_type='net'):
        """
        function for adding a row of constraints to the canonical optimization problem arrays: A, G, and h
        Note that upper_bounds and lower_bounds are Series, bound_weights is a DataFrame, ad x_init is a numpy array
        """

        if bound_type not in ['net', 'gross', 'long', 'short', 'quadratic',
                              'buys', 'sells', 'gross_turnover', 'net_turnover']:
            raise ValueError("bound_type has to be 'net', 'gross', 'long', 'short', 'quadratic'," +
                             " 'buys', 'sells', 'gross_turnover', or 'net_turnover'")

        # ensure bound_weights is a DataFrame and upper and lower bounds are Series
        bound_weights_index = [0]
        if isinstance(bound_weights, pd.DataFrame):
            bound_weights_index = bound_weights.index
        elif isinstance(upper_bounds, pd.Series):
            bound_weights_index = upper_bounds.index
        elif isinstance(lower_bounds, pd.Series):
            bound_weights_index = lower_bounds.index

        if isinstance(bound_weights, list):
            bound_weights = pd.DataFrame(bound_weights, columns=active_assets, index=bound_weights_index )
        elif isinstance(bound_weights, pd.Series):
            bound_weights = bound_weights.to_frame().T
        elif bound_weights is None:
            bound_weights = pd.DataFrame(1., columns=active_assets, index=bound_weights_index )
        if isinstance(upper_bounds, pd.Series):
            upper_bounds = pd.Series(upper_bounds, index=bound_weights.index)
        elif upper_bounds is None:
            upper_bounds = pd.Series(index=bound_weights.index)
        if isinstance(lower_bounds, pd.Series):
            lower_bounds = pd.Series(lower_bounds, index=bound_weights.index)
        elif lower_bounds is None:
            lower_bounds = pd.Series(index=bound_weights.index)

        if len(upper_bounds) != bound_weights.shape[0]:
            raise ValueError('number of upper bounds must match number of bounds specified')
        if len(lower_bounds) != bound_weights.shape[0]:
            raise ValueError('number of lower bounds must match number of bounds specified')

        weights_array = np.array(bound_weights[active_assets].fillna(0.0), ndmin=2, dtype=float)
        # np.array will upcast a constant to a singleton array, so we have a 1-dimensional array in all cases
        upper_bounds = np.array(upper_bounds, dtype=float, ndmin=1)
        lower_bounds = np.array(lower_bounds, dtype=float, ndmin=1)

        # pd.notnull handles both None and NaN, and the np.array calls above guarantee we have 1-D input.
        # An unconstrained optimization will have both bounds be [np.NaN] at this point.
        have_upper = pd.notnull(upper_bounds).any()
        have_lower = pd.notnull(lower_bounds).any()

        if have_upper or have_lower:
            covariance_array = np.array(constraint_covariance)

            if dimension_multiplier == 1:
                current_weights, D2, E2 = self.__compose_weighted_portfolio_constraint_d1(weights_array, x_init,
                                                                                          covariance_array, bound_type)
            elif dimension_multiplier == 2:
                current_weights, D2, E2 = self.__compose_weighted_portfolio_constraint_d2(weights_array, x_init,
                                                                                          covariance_array, bound_type)
            elif dimension_multiplier == 4:
                current_weights, D2, E2 = self.__compose_weighted_portfolio_constraint_d4(weights_array, x_init,
                                                                                          covariance_array, bound_type)
            else:
                raise ValueError('%d needs to be 4, 2, or 1' % dimension_multiplier)

            # add constraint for portfolio upper bound
            if have_upper:
                new_bound = upper_bounds - current_weights
                not_null = pd.notnull(new_bound)
                A += [x for (x, y) in zip(E2, not_null) if y]
                G = np.vstack((G, D2[not_null, :]))
                h = np.hstack((h, new_bound[not_null]))

            # add constraint for portfolio lower bound
            if have_lower:
                new_bound = lower_bounds - current_weights
                not_null = pd.notnull(new_bound)
                A += [x for (x, y) in zip(E2, not_null) if y]
                G = np.vstack((G, -D2[not_null, :]))
                h = np.hstack((h, -new_bound[not_null]))

        return A, G, h

    def __compose_weighted_portfolio_constraint_d1(self, weights_array, x_init, covariance_array, bound_type):
        """
        function to compose portfolio constraints of a specified type for when the optimization problem has not had
        to be upcast to a higher dimension
        """

        n = len(x_init)  # this is the number of assets
        m = weights_array.shape[0]  # the is the number of constraints passed

        if bound_type in ['net', 'net_turnover']:
            current_weights = np.zeros(m)
            if bound_type == 'net':
                current_weights = weights_array.dot(x_init)
            D2 = weights_array
            E2 = [None]*m

        elif bound_type == 'quadratic':
            current_weights = np.zeros(m)
            D2 = np.zeros((m, n))
            for i in range(m):
                weighted_x_init = x_init * weights_array[i, :]
                current_weights[i] = np.dot(weighted_x_init, np.dot(covariance_array, weighted_x_init))
                D2[i, :] = 2. * covariance_array.dot(weighted_x_init)

            E2 = [covariance_array] * m

        else:
            raise ValueError('invalid bound_type: "%s"' % bound_type)

        return current_weights, D2, E2

    def __compose_weighted_portfolio_constraint_d2(self, weights_array, x_init, covariance_array, bound_type):
        """
        function to compose portfolio constraints of a specified type where for when we've had to upcast the
        problem to a higher dimension to separate out buy trades and sell trades
        """

        n = len(x_init)  # this is the number of assets
        m = weights_array.shape[0]  # the is the number of constraints passed

        if bound_type == 'net':
            current_weights = weights_array.dot(x_init)
            D2 = np.hstack((weights_array, -weights_array))
            E2 = [None]*m

        elif bound_type == 'quadratic':
            current_weights = np.zeros(m)
            D2 = np.zeros((m, n))
            for i in range(m):
                weighted_x_init = x_init * weights_array[i, :]
                current_weights[i] = np.dot(weighted_x_init, np.dot(covariance_array, weighted_x_init))
                D2[i, :] = 2. * covariance_array.dot(weighted_x_init)

            D2 = np.hstack((D2, -D2))

            tmp = np.hstack((covariance_array, -covariance_array))
            big_covariance = np.vstack((tmp, -tmp))
            E2 = [big_covariance] * m

        elif bound_type in ['buys', 'sells', 'net_turnover', 'gross_turnover']:
            zeros = np.zeros((m, n))
            current_weights = np.zeros(m)

            D2 = None
            if bound_type == 'buys':
                D2 = np.hstack((weights_array, zeros))
            elif bound_type == 'sells':
                D2 = np.hstack((zeros, weights_array))
            elif bound_type == 'net_turnover':
                D2 = np.hstack((weights_array, -weights_array))
            elif bound_type == 'gross_turnover':
                D2 = np.hstack((weights_array, weights_array))

            E2 = [None]*m

        else:
            raise ValueError('invalid bound_type: "%s"' % bound_type)

        return current_weights, D2, E2

    def __compose_weighted_portfolio_constraint_d4(self, weights_array, x_init, covariance_array, bound_type):
        """
        function to compose portfolio constraints of a specified type for when we've had to upcast the
        problem to a higher dimension to separate out buying back shorts, buying longs, selling longs, and
        selling shorts
        """

        n = len(x_init)  # this is the number of assets
        m = weights_array.shape[0]  # the is the number of constraints passed

        if bound_type == 'net':
            current_weights = weights_array.dot(x_init)
            D2 = np.hstack((weights_array, weights_array, -weights_array, -weights_array))
            E2 = [None]*m

        elif bound_type == 'quadratic':
            current_weights = np.zeros(m)
            D2 = np.zeros((m, n))
            for i in range(m):
                weighted_x_init = x_init * weights_array[i, :]
                current_weights[i] = np.dot(weighted_x_init, np.dot(covariance_array, weighted_x_init))
                D2[i, :] = 2. * covariance_array.dot(weighted_x_init)

            D2 = np.hstack((D2, D2, -D2, -D2))

            tmp = np.hstack((covariance_array, covariance_array, -covariance_array, -covariance_array))
            big_covariance = np.vstack((tmp, tmp, -tmp, -tmp))
            E2 = [big_covariance] * m

        elif bound_type in ['buys', 'sells', 'net_turnover', 'gross_turnover']:
            current_weights = np.zeros(m)

            zeros = np.zeros((m, n))
            D2 = None
            if bound_type == 'buys':
                D2 = np.hstack((weights_array, weights_array, zeros, zeros))
            elif bound_type == 'sells':
                D2 = np.hstack((zeros, zeros, weights_array, weights_array))
            elif bound_type == 'net_turnover':
                D2 = np.hstack((weights_array, weights_array, -weights_array, -weights_array))
            elif bound_type == 'gross_turnover':
                D2 = np.hstack((weights_array, weights_array, weights_array, weights_array))

            E2 = [None]*m

        elif bound_type in ['gross', 'long', 'short']:
            long_locations = np.where(x_init >= 0)[0]
            short_locations = np.where(x_init < 0)[0]

            longs = np.zeros(4*n)
            longs[long_locations] = 1.  # needed to ensure buy short term for longs can't grow unbounded
            longs[long_locations + n] = 1.  # extending longs
            longs[long_locations + 2*n] = -1.  # reducing longs
            longs[short_locations + n] = 1.  # newly initiated longs

            shorts = np.zeros(4*n)
            shorts[long_locations + 3*n] = 1.  # newly initiated shorts
            shorts[short_locations] = -1  # reducing shorts
            shorts[short_locations + 2*n] = 1.  # needed to ensure sell long term for shorts can't grow unbounded
            shorts[short_locations + 3*n] = 1.  # extending shorts

            current_weights = None
            D2 = np.hstack((weights_array, weights_array, weights_array, weights_array))
            if bound_type == 'gross':
                D2 *= (longs + shorts)
                current_weights = weights_array.dot(abs(x_init))
            elif bound_type == 'long':
                D2 *= longs
                current_weights = weights_array[:, long_locations].dot(x_init[long_locations])
            elif bound_type == 'short':
                D2 *= shorts
                current_weights = weights_array[:, short_locations].dot(-x_init[short_locations])

            E2 = [None]*m

        else:
            raise ValueError('invalid bound_type: "%s"' % bound_type)

        return current_weights, D2, E2

    def __extend_problem_with_square_root_market_impact(self, P, q, A, G, h, k2, dimension_multiplier):
        """
        function to add square root market impact terms to the optimization problem.

        the extension here adds terms to the objective equal to k2_i*s_i*sum_j(t_{j,i})
        where sum_j(t_{j,i}) is the sum over the j trade types (buy_short, buy_long, sell_long, sell_short)
        for the ith asset, i.e. it is the total gross trading of the ith asset
        s_i is defined below by the quadratic equality constraint to be s_i^2 = sum_j(t_{j,i}),
        i.e. it is the squared total gross trading of the ith asset, which implies that
        the terms added here are k2_i times gross trading ^ 3/2 as can be seen by
        k2_i*s_i*sum_j(t_{j,i}) = k2_i*sum_j(t_{j,i})^(3/2)
        """

        # get problem size
        n = len(k2)

        # adjust quadratic objective term to include sqrt(gross_trade_size) terms
        # and impose the additional penalty on the 3/2 power of trade sizes
        market_impact_array = 0.5 * np.diag(k2)
        zeros = np.zeros((n, n))
        P = np.hstack((P, np.tile(market_impact_array, (dimension_multiplier, 1))))
        P = np.vstack((P, np.hstack((np.tile(market_impact_array, (1, dimension_multiplier)), zeros))))

        # adjust linear objective term to include sqrt(gross_trade_size) terms
        # no additional penalty imposed on the 1/2 power of trade sizes
        # q will already contain a linear penalty (i.e. 1 power) on the trade sizes
        q = np.hstack((q, np.zeros(n)))

        # adjust inequality constraints
        # add constraints that sqrt(gross_trade_size) >= 0
        G = np.hstack((G, np.zeros((G.shape[0], n))))
        G = np.vstack((G, np.hstack((np.tile(zeros, (1, dimension_multiplier)), -1 * np.eye(n)))))
        h = np.hstack((h, np.zeros(n)))
        A += [None]*n

        # create sqrt of trade size variables
        # x'Bx + Fx + k = 0
        B = []
        F = np.zeros((n, (dimension_multiplier+1)*n))
        k = np.zeros(n)
        for i in range(n):
            # create quadratic terms
            Btmp = np.zeros(((dimension_multiplier+1)*n, (dimension_multiplier+1)*n))
            Btmp[dimension_multiplier*n + i, dimension_multiplier*n + i] = 1.
            B.append(Btmp)

            # create linear terms
            for j in range(n):
                F[i, j*n + i] = -1.

        ##############################################################################################################
        ##############################################################################################################
        # cvxopt IS RETURNING THAT THE PROBLEM IS INFEASIBLE WITH THESE CONSTRAINTS ADDED. HAVEN'T YET IDENTIFIED WHY.
        ##############################################################################################################
        ##############################################################################################################

        # # add s^2 <= |t| to inequality constraints rather than equality constraints ???
        # G = np.vstack((G, F))
        # h = np.hstack((h, k))
        # A += B
        # # null out B so quadratic equality constraints aren't used ???
        # B = []

        return P, q, A, G, h, B, F, k

    def solve_qcqp_via_sdp_recasting(self, objective, inequality_constraints=None, equality_constraints=None, r=0.0):
        """
        function to solve qcqp problems in cvxopt by recasting them as sdp problems. cvxopt does not have a native
        qcqp solver, but it does have solvers that can handle these types of problems when they are recast into a
        more relaxed canonical structure (such as sdp)

        result = solve_qcqp_via_sdp_recasting(objective, inequality_constraints, equality_constraints, r)

        # based on qcqprel from http://pages.cs.wisc.edu/~kline/qcqp/

        # minimize   (1/2) * x' * P * x + q'* x
        # subject to   x' * A * x + G * x + h <= 0
        #              x' * Z * x + F * x + g = 0

        objective is dictionary with keys
            'P' is a symmetric matrix
            'q' is vector
            'c' is scalar

        inequality_constraints is dictionary with keys
            'A' is array of symmetric matrices
            'G' is array of vectors
            'h' is array of scalars

        equality_constraints is dictionary with keys
            'A' is array of symmetric matrices
            'G' is array of vectors
            'h' is array of scalars

        r is scalar, expected to be >=0

        r is optional 'trace weight'. The larger 'r' is, the more emphasis is
        given to 'trace(X)' being small. The emphasis is linear in 'r'.

        The arrays 'A', 'G' and 'h' expected to have equal length (and/or can be set to None)

        All entried in dictionaries are optional (and/or can be set to None)

        method attempts to find a good lower bound on the problem

        minimize   (1/2) * x' * P * x + q'* x
        subject to   x' * A * x + G * x + h <= 0
                     x' * Z * x + F * x + g = 0

        Returns a dictionary with keys corresponding to keys returned by
        cvxopt.solvers.sdp and with additional keys 'QCQPx', 'QCQPX'

        Let 'X':=QCQPX and 'x':=QCQPx. If qcqp_to_sdp returns a non-null answer,
        then it is guaranteed that X >= x*x.T

        qcqp_to_sdp is the 'relaxation' of 'QCQP', i.e. it relaxes the constraint
        X == x*x.T  to  X >= x*x.T
        """

        # get the objective
        if ('P' in objective) and (objective['P'] is not None):
            n = objective['P'].shape[0]
        elif ('q' in objective) and (objective['q'] is not None):
            n = objective['q'].shape[0]
        else:
            raise ValueError("objective needs to contain either 'P'' or 'q'")

        I = cvxopt.matrix(0., (n, n))
        I[::n+1] = r  # set the diagonal equal to r

        if 'P' not in objective:
            objective['P'] = I
        else:
            objective['P'] += I
        if 'q' not in objective:
            objective['q'] = None
        if 'c' not in objective:
            objective['c'] = None

        c = self.build_column_major_equivalent_vec(objective['P'], objective['q'], objective['c'])

        # build the inequality constraints
        Gl, hl = self.build_semidefinite_constraint_structures(inequality_constraints, c.size[0])

        # built the equality constraints
        A, b = self.build_semidefinite_constraint_structures(equality_constraints, c.size[0])
        # pre-pend constraint on first entry, the constant entry, to be 1.
        A = cvxopt.matrix([cvxopt.matrix(0., (1, c.size[0])), A])
        A[0] = 1.
        b = cvxopt.matrix([1., b])

        # get the "semidef" matrix
        Gs = self.build_default_semidefinite_constraints_matrix(n+1)
        hs = cvxopt.matrix(0., (n+1, n+1))

        # solve the problem
        cvxopt.solvers.options['show_progress'] = False
        result = cvxopt.solvers.sdp(c, Gl, hl, [Gs], [hs], A, b)

        # build the solution to return
        if result['status'] == 'optimal':
            # pull out result
            x = result['x']

            # return the solution in matrix form as it is seen by sdp
            Y = x[n+1:]
            YY = cvxopt.matrix(0., (n, n))
            J = 0
            for j in range(n):
                for k in range(j, n):
                    YY[j, k] = Y[J]
                    YY[k, j] = Y[J]
                    J += 1
            result['QCQPX'] = YY

            # also return the solution in the regular vector form
            # over-writing the output x with the uncasted result
            result['QCQPx'] = x
            result['x'] = x[1:n+1]

        else:
            result['QCQPx'] = None
            result['QCQPX'] = None

        return result

    def build_column_major_equivalent_vec(self, Q=None, a=None, b=None):
        """
        x Q x + a'x + b <= 0
        is converted to
        <q,X> <= 0
        where q is returned by this function

        Input
        Q size nxn
        a size nx1
        b is scalar

        Output
        c size (n+1)*(n+2)/2 x 1
        """

        if Q is not None:
            n = Q.shape[0]
        elif a is not None:
            n = a.shape[0]
        else:
            raise ValueError('one of Q or a must be specified')
        if Q is None:
            Q = cvxopt.matrix(0., (n, n))
        if a is None:
            a = cvxopt.matrix(0., (n, 1))
        if b is None:
            b = 0.

        # convert inputs to cvxopt format
        b = cvxopt.matrix(b)
        a = cvxopt.matrix(a)
        Q = cvxopt.matrix(Q)

        # create column major version of constraint in vec form
        Qtmp = cvxopt.matrix([[b, a*0.5], [a.T*0.5, Q]])
        q = cvxopt.matrix(0., ((n+1)*(n+2)//2, 1))
        jdx = 0
        for j in range(n+1):
            idx = cvxopt.matrix(range(j, n+1))
            tmp = Qtmp[idx, j]
            tmp[1:] *= 2.
            q[jdx+idx] = tmp
            jdx += len(idx) - 1

        return q

    def build_semidefinite_constraint_structures(self, constraint_dict, n):
        """
        function to build the constraint structures for the sdp solver from the constraint structures
        that are normally used for simpler solvers like qp.

        x' A x + G'x + h <= 0
        is converted to
        <q,X> <= 0
        where q is returned by this function

        Input:
            constraint_dict with keys A, G, and h which are each lists/arrays specifying the different constraints

        Output
        G size m x (n+1)*(n+2)/2
        h size m x 1
        where m is the number of constraints specified by the dict passed in
        """

        # build the constraints
        if constraint_dict is None:
            constraint_dict = {}
        m = 0
        if ('A' in constraint_dict) and (constraint_dict['A'] is not None):
            m = len(constraint_dict['A'])
        elif ('G' in constraint_dict) and (constraint_dict['G'] is not None):
            m = len(constraint_dict['G'])
        elif ('h' in constraint_dict) and (constraint_dict['h'] is not None):
            m = len(constraint_dict['h'])
        if ('A' not in constraint_dict) or (constraint_dict['A'] is None):
            constraint_dict['A'] = [None]*m
        if ('G' not in constraint_dict) or (constraint_dict['G'] is None):
            constraint_dict['G'] = [None]*m
        if ('h' not in constraint_dict) or (constraint_dict['h'] is None):
            constraint_dict['h'] = [None]*m
        # initialize the constraints
        G = cvxopt.matrix(0., (0, n))
        for j in range(m):
            q = self.build_column_major_equivalent_vec(constraint_dict['A'][j],
                                                       constraint_dict['G'][j],
                                                       constraint_dict['h'][j])
            G = cvxopt.matrix([G, q.T])
        h = cvxopt.matrix(0., (G.size[0], 1))

        return G, h

    def build_default_semidefinite_constraints_matrix(self, n):
        """
        function returns the sparse 'sdp' constraint matrix Q that
        sets up the constraint:
            Force the matrix
            [ Y ] >= H
        where H is some nxn matrix, (not specified here)

        n is an integer, the size of the matrix we want
        """

        m = n*(n+1)//2
        Q = cvxopt.matrix(0., (n**2, m))
        J = 0
        for j in range(n):
            for k in range(j, n):
                Q[k+j*n, J] = -1.
                J += 1
        Q = cvxopt.sparse(Q)

        return Q
