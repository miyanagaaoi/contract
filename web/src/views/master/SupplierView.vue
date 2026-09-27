<script setup lang="ts">
/** 供应商信息（T-V2-07 / AC-V2-12）。 */
import MasterTablePage from '@/components/MasterTablePage.vue'
import type { MasterColumn, MasterField } from '@/types/master'

const columns: MasterColumn[] = [
  { prop: 'code', label: '编码', width: 110 },
  // V2.2：简称放到名称前面——它是单据、下拉与口头沟通里真正用来指代的字段
  { prop: 'short_name', label: '简称', width: 130 },
  { prop: 'name', label: '供应商名称', minWidth: 180 },
  { prop: 'contact_name', label: '联系人', width: 100 },
  { prop: 'contact_phone', label: '联系电话', width: 130 },
  { prop: 'supply_scope', label: '供货范围', minWidth: 140 },
  { prop: 'payment_days', label: '账期(天)', width: 90 },
  { prop: 'level', label: '等级', width: 70 },
  { prop: 'status', label: '状态', width: 80, kind: 'status' },
]

const fields: MasterField[] = [
  { prop: 'name', label: '供应商名称', required: true, span: 24 },
  { prop: 'code', label: '供应商编码', placeholder: '留空自动生成（SUP+序号）' },
  // V2.2（BR-V2.2-01）：简称由选填改为必填（录入顺序也提前到名称之后）
  { prop: 'short_name', label: '简称', required: true, placeholder: '单据与下拉里显示的名称' },
  {
    prop: 'level', label: '等级', type: 'select',
    options: ['A', 'B', 'C', 'D'].map((v) => ({ label: v, value: v })),
  },
  { prop: 'contact_name', label: '联系人' },
  { prop: 'contact_phone', label: '联系电话' },
  { prop: 'tax_no', label: '税号' },
  { prop: 'bank_name', label: '开户行' },
  { prop: 'bank_account', label: '银行账号' },
  { prop: 'payment_days', label: '账期(天)', type: 'number', min: 0 },
  { prop: 'supply_scope', label: '供货范围', span: 24 },
  { prop: 'address', label: '地址', span: 24 },
  { prop: 'remark', label: '备注', type: 'textarea', span: 24 },
]
</script>

<template>
  <MasterTablePage title="供应商信息" subtitle="采购方向的乙方档案；简称必填，单据与下拉按简称显示"
                   api="/master/suppliers"
                   perm-edit="master.supplier.edit" :columns="columns" :fields="fields"
                   keyword-placeholder="名称 / 编码 / 简称 / 联系人" />
</template>
