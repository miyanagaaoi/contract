<script setup lang="ts">
/**
 * 通用「快速新增主数据」弹窗（V2.1 / N9 · N15）。
 *
 * 解决的问题：在**单据行项**或**物料档案**里发现"要录的物料/商品类型/计量单位还没有"时，
 * 传统做法是跳到主数据页新增再回来——**当前未保存的表单会丢**。
 * BR-V2.1-10 明确禁止这种跳转，因此本组件在当前页以弹窗完成新增，
 * 保存后把新档案回传给调用方自动回填。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { createMasterItem, fetchMasterList, type Dict } from '@/api'

const props = defineProps<{ kind: 'product' | 'product-type' | 'uom' }>()
const emit = defineEmits<{ created: [item: Dict] }>()

const TITLE: Record<string, string> = {
  product: '新增物料档案', 'product-type': '新增商品类型', uom: '新增计量单位',
}
const PATH: Record<string, string> = {
  product: '/products', 'product-type': '/product-types', uom: '/uoms',
}

const visible = ref(false)
const saving = ref(false)
const form = ref<Dict>({})
const typeTree = ref<Dict[]>([])
const uoms = ref<Dict[]>([])

const title = computed(() => TITLE[props.kind] ?? '新增档案')

function reset() {
  if (props.kind === 'product') {
    form.value = { name: '', spec: '', product_type_id: null, uom_id: null, default_price: 0 }
  } else if (props.kind === 'product-type') {
    form.value = { name: '', code: '', parent_id: null }
  } else {
    form.value = { code: '', name: '', decimals: 2 }
  }
}

/** 打开弹窗（每次重置，避免残留上次输入） */
async function open() {
  reset()
  visible.value = true
  try {
    if (props.kind === 'product' || props.kind === 'product-type') {
      const res: Dict = await fetchMasterList('/product-types')
      typeTree.value = (res.tree ?? res.items ?? []) as Dict[]
    }
    if (props.kind === 'product') {
      const res: Dict = await fetchMasterList('/uoms')
      uoms.value = (res.items ?? []) as Dict[]
    }
  } catch {
    // 下拉加载失败不阻塞弹窗
  }
}

async function save() {
  const f = form.value
  if (props.kind === 'uom') {
    if (!f.code || !f.name) { ElMessage.warning('编码与名称必填'); return }
  } else if (!f.name) {
    ElMessage.warning('名称必填')
    return
  }
  if (props.kind === 'product' && (!f.product_type_id || !f.uom_id)) {
    ElMessage.warning('请选择商品类型与计量单位')
    return
  }
  saving.value = true
  try {
    const payload: Dict = { ...f }
    if (!payload.parent_id) delete payload.parent_id
    const item = await createMasterItem(PATH[props.kind], payload)
    ElMessage.success('已新增并回填到当前表单')
    visible.value = false
    emit('created', item)
  } catch {
    // 拦截器已提示
  } finally {
    saving.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <el-dialog v-model="visible" :title="title" width="480px" append-to-body>
    <el-form label-width="92px" :disabled="saving">
      <template v-if="kind === 'uom'">
        <el-form-item label="编码" required>
          <el-input v-model="form.code" maxlength="16" placeholder="如 PCS" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="32" placeholder="如 个" />
        </el-form-item>
        <el-form-item label="小数位">
          <el-input-number v-model="form.decimals" :min="0" :max="6" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </template>

      <template v-else-if="kind === 'product-type'">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="form.code" maxlength="32" placeholder="物料编码前缀来源，可空" />
        </el-form-item>
        <el-form-item label="上级类型">
          <el-tree-select v-model="form.parent_id" :data="typeTree" clearable check-strictly
                          :props="{ label: 'name', value: 'id', children: 'children' }"
                          placeholder="不选则建为根节点" style="width: 100%" />
        </el-form-item>
      </template>

      <template v-else>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="规格型号">
          <el-input v-model="form.spec" maxlength="128" />
        </el-form-item>
        <el-form-item label="商品类型" required>
          <el-tree-select v-model="form.product_type_id" :data="typeTree" check-strictly filterable
                          :props="{ label: 'name', value: 'id', children: 'children',
                                    disabled: (d: Dict) => !!(d.children && d.children.length) }"
                          placeholder="只能选择叶子类型" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计量单位" required>
          <el-select v-model="form.uom_id" filterable style="width: 100%">
            <el-option v-for="u in uoms" :key="u.id" :label="`${u.name}（${u.code}）`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="默认单价">
          <el-input-number v-model="form.default_price" :min="0" :precision="4" :controls="false"
                           style="width: 100%" />
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存并回填</el-button>
    </template>
  </el-dialog>
</template>
