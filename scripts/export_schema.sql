set pages 0
set feedback off
set verify off
set heading off
set echo off
set linesize 32767
set long 50000000
set longchunksize 50000000
set trimspool on
whenever oserror exit 1
whenever sqlerror exit sql.sqlcode

with
table_columns as (
    select
        utc.table_name,
        json_arrayagg(
            json_object(
                'name' value utc.column_name,
                'data_type' value utc.data_type,
                'nullable' value utc.nullable,
                'data_length' value utc.data_length,
                'data_precision' value utc.data_precision,
                'data_scale' value utc.data_scale,
                'column_id' value utc.column_id
                returning clob
            )
            order by utc.column_id
            returning clob
        ) as columns_json
    from user_tab_columns utc
    group by utc.table_name
),
primary_keys as (
    select
        uc.table_name,
        json_arrayagg(ucc.column_name order by ucc.position returning clob) as pk_columns
    from user_constraints uc
    join user_cons_columns ucc
        on ucc.constraint_name = uc.constraint_name
    where uc.constraint_type = 'P'
    group by uc.table_name
),
foreign_keys as (
    select
        uc.table_name,
        json_arrayagg(
            json_object(
                'constraint_name' value uc.constraint_name,
                'column_name' value child_col.column_name,
                'referenced_table' value parent_uc.table_name,
                'referenced_column' value parent_col.column_name
                returning clob
            )
            order by uc.constraint_name, child_col.position
            returning clob
        ) as fk_json
    from user_constraints uc
    join user_cons_columns child_col
        on child_col.constraint_name = uc.constraint_name
    join user_constraints parent_uc
        on parent_uc.constraint_name = uc.r_constraint_name
    join user_cons_columns parent_col
        on parent_col.constraint_name = parent_uc.constraint_name
       and parent_col.position = child_col.position
    where uc.constraint_type = 'R'
    group by uc.table_name
)
select json_object(
        'owner' value user,
        'tables' value (
            select json_arrayagg(
                json_object(
                    'name' value ut.table_name,
                    'columns' value coalesce(tc.columns_json, json_array(returning clob)) format json,
                    'primary_key' value coalesce(pk.pk_columns, json_array(returning clob)) format json,
                    'foreign_keys' value coalesce(fk.fk_json, json_array(returning clob)) format json
                    returning clob
                )
                order by ut.table_name
                returning clob
            )
            from user_tables ut
            left join table_columns tc
                on tc.table_name = ut.table_name
            left join primary_keys pk
                on pk.table_name = ut.table_name
            left join foreign_keys fk
                on fk.table_name = ut.table_name
        ) format json,
        'views' value (
            select json_arrayagg(
                json_object('name' value uv.view_name)
                order by uv.view_name
                returning clob
            )
            from user_views uv
        ) format json,
        'synonyms' value (
            select json_arrayagg(
                json_object(
                    'name' value us.synonym_name,
                    'table_owner' value us.table_owner,
                    'table_name' value us.table_name
                    returning clob
                )
                order by us.synonym_name
                returning clob
            )
            from user_synonyms us
        ) format json
    returning clob
)
from dual;
exit
