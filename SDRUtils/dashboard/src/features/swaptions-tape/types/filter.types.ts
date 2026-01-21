// Filter types for trade tape

export type ColumnFilterConstraint = {
  value: any;
  matchMode?: string;
};

export type ColumnFilterPayload = Record<
  string,
  {
    operator?: string;
    constraints: ColumnFilterConstraint[];
  }
>;
