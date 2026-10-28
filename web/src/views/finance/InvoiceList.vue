<script setup lang="ts">
/**
 * 发票管理（V2.5 AC-V2.5-09~11；V2.6 同步与列改造，docs/38）。
 *
 * 进项/销项同表：列表按 `direction` 分页签（用「方向」筛选项切换），
 * 认证状态（待认证/已认证）由财务手工流转，**不影响**收票/开票进度；
 * 「确认入账」才是记账动作（回写目标单据的 `invoiced_amount`）。
 *
 * V2.6 改造：
 * - 「⟳ 同步发票」从电子发票服务平台拉取进项发票（同步 = 已认证，未确认）；
 * - 列口径：开票日期默认倒序可切换；签约公司 / 开票单位（销方）/ 收票单位（购方）；
 *   税率列新增；金额移到税额后；
 * - 确认状态徽标（未确认/已确认）随绑定弹窗流转。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DocListPage from '@/components/doc/DocListPage.vue'
import {
  confirmInvoice, downloadWithAuth, fetchInvoiceFiles, importInvoiceFile,
  printInvoicePackages, unbindInvoice, verifyInvoice, voidInvoice, type Dict,
} from '@/api'
import { useAuthStore } from '@/stores/auth'
import { fmtDate, fmtMoney } from '@/utils/format'
import type { DocRecord } from '@/types/doc'

const auth = useAuthStore()
const listRef = ref<InstanceType<typeof DocListPage> | null>(null)
const direction = ref<string>('in')
const authStatus = ref<string>('')
const bindStatus = ref<string>('')
const hasFile = ref<string>('')
const invoiceType = ref<string>('')
const sort = ref<string>('invoice_date_desc')
const uploadBusy = ref(false)

const filterParams = computed<Dict>(() => ({
  direction: direction.value || undefined,
  auth_status: authStatus.value || undefined,
  bind_status: bindStatus.value || undefined,
  has_file: hasFile.value === '' ? undefined : hasFile.value,
  invoice_type: invoiceType.value || undefined,
  sort: sort.value,
}))

const canConfirm = computed(() => auth.hasPerm('finance.invoice.confirm'))
const canVoid = computed(() => auth.hasPerm('finance.invoice.void'))
const canSync = computed(() => auth.hasPerm('finance.invoice.create'))



function flash(message: string) {
  ElMessage.success(message)
  listRef.value?.load()
}


/** 批量打印：把所选发票的原始 PDF 合并成一个文件在新窗口打开 */
async function printBulk(selected: DocRecord[]) {
  const withFile = selected.filter((r) => r.has_pdf)
  if (!withFile.length) {
    ElMessage.warning('所选发票均未上传原始文件：请先在税务平台下载发票包并「上传发票包」导入。')
    return
  }
  if (withFile.length < selected.length) {
    ElMessage.info(`${selected.length - withFile.length} 张未上传原始文件，已跳过`)
  }
  try {
    const blob = await printInvoicePackages(withFile.map((r) => r.id))
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank')
    ElMessage.success(`已合并 ${withFile.length} 张发票原始文件，可在新窗口打印/保存`)
  } catch { /* 拦截器已提示 */ }
}

const pkgInput = ref<HTMLInputElement | null>(null)


async /** CR-026：上传单张 PDF 或 ZIP 发票包 → 识别 → 建单/挂附件，并刷新列表 */
async function onPackagePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploadBusy.value = true
  try {
    const res = await importInvoiceFile(file)
    const created = (res.created || []).length
    const attached = (res.attached || []).length
    const failed = (res.failed || []) as Dict[]
    ElMessage.success(`已处理：新建发票 ${created} 张，补挂附件 ${attached} 张`
      + (failed.length ? `，失败 ${failed.length} 个` : ''))
    if (failed.length) {
      await ElMessageBox.alert(
        failed.slice(0, 10).map((f) => `· ${f.file}：${f.reason}`).join('\n'),
        '以下文件未能识别', { type: 'warning', confirmButtonText: '知道了' })
    }
    listRef.value?.load()
  } catch { /* 拦截器已提示 */ } finally {
    uploadBusy.value = false
  }
}

async function onMore({ command, row }: { command: string; row: DocRecord }) {
  try {
    if (command === 'invoice-print') {
      const files = await fetchInvoiceFiles(row.id)
      const pdf = files.find((f) => f.is_pdf)
      if (!pdf) {
        ElMessage.warning(
          '该发票还没有原始文件：请在税务平台「下载→全部下载」后，用列表上方「上传发票包」导入。')
        return
      }
      // 直链打开不带登录态 → 经 axios（带 token）取 blob 再打开
      const blob = await downloadWithAuth(String(pdf.preview_url))
      window.open(URL.createObjectURL(blob), '_blank')
      return
    }
    if (command === 'invoice-confirm') {
      await ElMessageBox.confirm(
        `确认发票 ${row.invoice_no} 入账？确认后计入对应单据的收票/开票进度（含税口径）。`,
        '确认入账', { type: 'info', confirmButtonText: '确认入账', cancelButtonText: '取消' })
      await confirmInvoice(row.id)
      flash('已确认入账')
      return
    }
    if (command === 'invoice-verify' || command === 'invoice-unverify') {
      const next = command === 'invoice-verify' ? 'verified' : 'pending'
      await verifyInvoice(row.id, next)
      flash(next === 'verified' ? '已标记为已认证' : '已退回待认证')
      return
    }
    if (command === 'invoice-unbind') {
      await ElMessageBox.confirm(
        `解绑发票 ${row.invoice_no}？将删除核销明细并重算收票进度，发票回到「未确认」。`,
        '解绑发票', { type: 'warning', confirmButtonText: '解绑', cancelButtonText: '取消' })
      await unbindInvoice(row.id)
      flash('已解绑，收票进度已重算')
      return
    }
    if (command === 'invoice-void') {
      const { value } = await ElMessageBox.prompt('作废原因（必填）', '作废发票', {
        type: 'warning', confirmButtonText: '确定作废', cancelButtonText: '取消',
        inputValidator: (v: string) => (v && v.trim() ? true : '请填写作废原因'),
      })
      await voidInvoice(row.id, value)
      flash('发票已作废（已确认的已红冲）')
    }
  } catch {
    // 取消或后端校验失败（拦截器已提示）
  }
}
</script>

<template>
  <DocListPage ref="listRef" title="发票管理" api="/api/finance/invoices"
               subtitle="进项/销项发票登记与同步；确认后计入收票/开票进度（含税口径）"
               perm-prefix="finance.invoice" kind-label="发票"
               form-route="finance-invoice-form" edit-route="finance-invoice-edit"
               detail-route="finance-invoice-detail" show-subject subject-label="收票单位"
               :printable="false"
               :extra-filter-params="filterParams"
               export-path="/api/finance/invoices/export.xlsx" @more="onMore">
    <!-- V2.6：同步发票入口（财务/有创建权限者可见） -->
    <template #toolbar>
      <el-tooltip content="上传单张发票 PDF，或税务平台「下载→全部下载」得到的 ZIP 发票包；自动识别票面并入库" placement="top">
        <el-button type="primary" plain :loading="uploadBusy" @click="pkgInput?.click()">
          上传发票（PDF / ZIP）
        </el-button>
      </el-tooltip>
      <input ref="pkgInput" type="file" accept=".pdf,.zip" style="display: none"
             @change="onPackagePicked" />
    </template>

    <template #extra-filters="{ reload }">
      <el-form-item label="方向">
        <el-select v-model="direction" style="width: 120px" @change="reload">
          <el-option label="进项发票" value="in" />
          <el-option label="销项发票" value="out" />
        </el-select>
      </el-form-item>
      <el-form-item label="票种">
        <el-select v-model="invoiceType" clearable filterable style="width: 190px"
                   placeholder="全部" @change="reload">
          <el-option label="数电发票（增值税专用发票）" value="数电发票（增值税专用发票）" />
          <el-option label="数电发票（普通发票）" value="数电发票（普通发票）" />
          <el-option label="增值税专用发票" value="增值税专用发票" />
          <el-option label="增值税普通发票" value="增值税普通发票" />
          <el-option label="电子发票" value="电子发票" />
        </el-select>
      </el-form-item>
      <el-form-item label="认证">
        <el-select v-model="authStatus" clearable style="width: 110px" placeholder="全部"
                   @change="reload">
          <el-option label="待认证" value="pending" />
          <el-option label="已认证" value="verified" />
        </el-select>
      </el-form-item>
      <el-form-item label="确认">
        <el-select v-model="bindStatus" clearable style="width: 110px" placeholder="全部"
                   @change="reload">
          <el-option label="未确认" value="unbound" />
          <el-option label="已确认" value="bound" />
        </el-select>
      </el-form-item>
      <el-form-item label="原始文件">
        <el-select v-model="hasFile" clearable style="width: 110px" placeholder="全部"
                   @change="reload">
          <el-option label="已下载" value="true" />
          <el-option label="未上传" value="false" />
        </el-select>
      </el-form-item>
      <el-form-item label="排序">
        <el-select v-model="sort" style="width: 170px" @change="reload">
          <el-option label="开票日期 ↓" value="invoice_date_desc" />
          <el-option label="开票日期 ↑" value="invoice_date_asc" />
          <el-option label="录入顺序" value="id_desc" />
        </el-select>
      </el-form-item>
    </template>

    <template #extra-columns>
      <el-table-column label="发票号码" width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ row.invoice_no }}</template>
      </el-table-column>
      <el-table-column label="票种" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="row.is_red" type="danger" size="small" style="margin-right: 4px">红冲</el-tag>
          {{ row.invoice_type || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="开票日期" width="100" sortable
                       :sort-by="(r: DocRecord) => r.invoice_date || ''"
                       :sort-method="undefined">
        <template #default="{ row }">{{ fmtDate(row.invoice_date) }}</template>
      </el-table-column>
      <el-table-column label="开票单位" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.seller_name || (row.invoice_direction === 'in' ? row.party_name : '—') || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="收票单位" width="130" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.buyer_name || row.our_company_name || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="税率" width="70" align="right">
        <template #default="{ row }">
          {{ row.tax_rate != null && row.tax_rate !== '' ? Number(row.tax_rate) + '%' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="税额" width="100" align="right">
        <template #default="{ row }">{{ fmtMoney(row.tax_amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="金额" width="115" align="right">
        <template #default="{ row }">{{ fmtMoney(row.amount || 0) }}</template>
      </el-table-column>
      <el-table-column label="认证 / 确认 / 文件" width="200">
        <template #default="{ row }">
          <el-tag :type="row.auth_status === 'verified' ? 'success' : 'warning'" size="small">
            {{ row.auth_status === 'verified' ? '已认证' : '待认证' }}
          </el-tag>
          <el-tag :type="row.bind_status === 'bound' ? 'success' : 'info'" size="small"
                  style="margin-left: 4px">
            {{ row.bind_status === 'bound' ? '已确认' : '未确认' }}
          </el-tag>
          <el-tooltip :content="row.has_pdf ? '已挂原始文件，可打印' :
                                '未上传原始文件（发票包）'" placement="top">
            <el-tag :type="row.has_pdf ? 'success' : 'info'" size="small"
                    style="margin-left: 4px" effect="plain">
              {{ row.has_pdf ? '已下载' : '未上传' }}
            </el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="同步时间" width="140">
        <template #default="{ row }">
          <span v-if="row.sync_source === 'tax_platform'"
                class="muted">{{ String(row.synced_at || '').replace('T', ' ').slice(0, 16) }}</span>
          <span v-else class="muted">—（手工）</span>
        </template>
      </el-table-column>
    </template>

    <!-- 「更多」里的发票动作：打印发票 / 确认入账 / 认证状态 / 解绑 / 作废 -->
    <template #more-actions="{ row }">
      <el-dropdown-item v-if="canConfirm" divided
                        command="invoice-print">打印发票</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.status === 'draft'"
                        command="invoice-confirm">确认入账</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.status !== 'voided'
                              && row.auth_status !== 'verified'"
                        command="invoice-verify">标记已认证</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.status !== 'voided'
                              && row.auth_status === 'verified'"
                        command="invoice-unverify">退回待认证</el-dropdown-item>
      <el-dropdown-item v-if="canConfirm && row.bind_status === 'bound'
                              && row.status !== 'voided'"
                        command="invoice-unbind">解绑采购单</el-dropdown-item>
      <el-dropdown-item v-if="canVoid && row.status !== 'voided'"
                        command="invoice-void">作废</el-dropdown-item>
    </template>

    <!-- 全选后的批量操作：打印发票原始文件（合并 PDF） -->
    <template #bulk-actions="{ selected }">
      <el-button v-if="canConfirm" type="primary" size="small"
                 @click="printBulk(selected as DocRecord[])">批量打印</el-button>
    </template>

    <template #detail-head="{ detail }">
      <el-descriptions-item label="打印">
        <el-button link type="primary" @click="onMore({ command: 'invoice-print', row: detail })">
          打印发票（原始文件）
        </el-button>
      </el-descriptions-item>
      <el-descriptions-item label="方向">
        {{ detail.invoice_direction_label || detail.invoice_direction }}
      </el-descriptions-item>
      <el-descriptions-item label="发票代码">{{ detail.invoice_code || '—' }}</el-descriptions-item>
      <el-descriptions-item label="开票日期">{{ fmtDate(detail.invoice_date) }}</el-descriptions-item>
      <el-descriptions-item label="票种">{{ detail.invoice_type || '—' }}</el-descriptions-item>
      <el-descriptions-item label="税率">
        {{ detail.tax_rate != null && detail.tax_rate !== '' ? Number(detail.tax_rate) + '%' : '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="金额 / 税额 / 价税合计">
        {{ fmtMoney(detail.amount || 0) }} / {{ fmtMoney(detail.tax_amount || 0) }}
        / {{ fmtMoney(detail.total_amount || 0) }}
      </el-descriptions-item>
      <el-descriptions-item label="开票单位">{{ detail.seller_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="收票单位">{{ detail.buyer_name || '—' }}</el-descriptions-item>
      <el-descriptions-item label="签约公司">
        {{ detail.our_company_name || detail.subject_name || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="认证 / 确认">
        {{ detail.auth_status === 'verified' ? '已认证' : '待认证' }} /
        {{ detail.bind_status === 'bound' ? '已确认' : '未确认' }}
      </el-descriptions-item>
      <el-descriptions-item label="同步时间">
        <template v-if="detail.sync_source === 'tax_platform'">
          {{ String(detail.synced_at || '').replace('T', ' ').slice(0, 16) }}
        </template>
        <template v-else>—（手工录入）</template>
      </el-descriptions-item>
      <el-descriptions-item label="已核销">{{ fmtMoney(detail.allocated_amount || 0) }}</el-descriptions-item>
      <el-descriptions-item label="未核销">{{ fmtMoney(detail.unallocated_amount || 0) }}</el-descriptions-item>
    </template>
  </DocListPage>

</template>

<style scoped>
.muted { color: var(--el-text-color-secondary); font-size: 12px }
</style>
