<script setup lang="ts">
import { Document, UploadFilled, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

const emit = defineEmits<{
  send: [content: string, attachmentIds: string[]]
  upload: [file: File]
}>()

const inputText = ref('')
const attachedFiles = ref<{ id: string; name: string }[]>([])
const isComposing = ref(false)

function handleSend() {
  const content = inputText.value.trim()
  if (!content) return

  const ids = attachedFiles.value.map(f => f.id)
  emit('send', content, ids)
  inputText.value = ''
  attachedFiles.value = []
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing.value) {
    e.preventDefault()
    handleSend()
  }
}

function handleFileChange(file: any) {
  const rawFile = file.raw || file
  if (rawFile.type !== 'application/pdf') {
    ElMessage.warning('仅支持 PDF 格式文件')
    return false
  }
  if (rawFile.size > 20 * 1024 * 1024) {
    ElMessage.warning('文件大小不能超过 20MB')
    return false
  }
  emit('upload', rawFile)
  return false // Prevent default upload
}

function addAttachment(id: string, name: string) {
  attachedFiles.value.push({ id, name })
}

function removeAttachment(index: number) {
  attachedFiles.value.splice(index, 1)
}

defineExpose({ addAttachment })
</script>

<template>
  <div class="input-bar">
    <div v-if="attachedFiles.length" class="attachments">
      <el-tag
        v-for="(file, index) in attachedFiles"
        :key="file.id"
        closable
        type="info"
        @close="removeAttachment(index)"
      >
        <el-icon><Document /></el-icon>
        {{ file.name }}
      </el-tag>
    </div>
    <div class="input-row">
      <el-upload
        :show-file-list="false"
        :before-upload="handleFileChange"
        accept=".pdf"
      >
        <el-button :icon="UploadFilled" circle />
      </el-upload>
      <el-input
        v-model="inputText"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 4 }"
        placeholder="输入你的研究问题..."
        @keydown="handleKeydown"
        @compositionstart="isComposing = true"
        @compositionend="isComposing = false"
        resize="none"
      />
      <el-button
        type="primary"
        :icon="Promotion"
        circle
        :disabled="!inputText.trim()"
        @click="handleSend"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.input-bar {
  padding: 12px 20px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
}

.attachments {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;

  .el-input {
    flex: 1;
  }
}
</style>
