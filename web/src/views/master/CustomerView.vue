<script setup lang="ts">
/** 客户信息（T-V2-07 / AC-V2-12）：编码自动生成、启停用、被合同引用时禁止删除。 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '编码', width: 110 },
  { prop: 'name', label: '客户名称', minWidth: 180 },
  { prop: 'short_name', label: '简称', width: 110 },
  { prop: 'contact_name', label: '联系人', width: 100 },
  { prop: 'contact_phone', label: '联系电话', width: 130 },
  { prop: 'level', label: '等级', width: 70 },
  { prop: 'credit_limit', label: '授信额度', width: 120, kind: 'money' },
  { prop: 'status', label: '状态', width: 80, kind: 'status' },
]

const fields: MasterField[] = [
  { prop: 'name', label: '客户名称', required: true, span: 24 },
  { prop: 'code', label: '客户编码', placeholder: '留空自动生成（CUS+序号）' },
  { prop: 'short_name', label: '简称' },
  {
    prop: 'level', label: '等级', type: 'select',
    options: ['A', 'B', 'C', 'D'].map((v) => ({ label: v, value: v })),
  },
  { prop: 'contact_name', label: '联系人' },
  { prop: 'contact_phone', label: '联系电话' },
  { prop: 'tax_no', label: '税号' },
  { prop: 'bank_name', label: '开户行' },
  { prop: 'bank_account', label: '银行账号' },
  { prop: 'credit_limit', label: '授信额度', type: 'number', precision: 2, min: 0 },
  { prop: 'address', label: '地址', span: 24 },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]
</script>

<template>
  <MasterTablePage title="客户信息" subtitle="销售方向的甲方档案；合同表单可按类型引用"
                   api="/master/customers"
                   perm-edit="master.customer.edit" :columns="columns" :fields="fields"
                   keyword-placeholder="名称 / 编码 / 简称 / 联系人" />
</template>
