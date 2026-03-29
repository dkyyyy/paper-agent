<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{
  content: string
}>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

const rendered = computed(() => md.render(props.content))
</script>

<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<style lang="scss">
.markdown-body {
  line-height: 1.7;
  color: #303133;
  word-break: break-word;

  h1, h2, h3, h4 {
    margin: 16px 0 8px;
    font-weight: 600;
  }

  h2 { font-size: 1.3em; }
  h3 { font-size: 1.1em; }

  p { margin: 8px 0; }

  ul, ol {
    padding-left: 24px;
    margin: 8px 0;
  }

  code {
    background: #f5f7fa;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 0.9em;
    font-family: 'Fira Code', monospace;
  }

  pre {
    background: #f5f7fa;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 12px 0;

    code {
      background: none;
      padding: 0;
    }
  }

  table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;

    th, td {
      border: 1px solid #dcdfe6;
      padding: 8px 12px;
      text-align: left;
    }

    th {
      background: #f5f7fa;
      font-weight: 600;
    }

    tr:hover td {
      background: #f5f7fa;
    }
  }

  blockquote {
    border-left: 4px solid #409eff;
    padding: 8px 16px;
    margin: 12px 0;
    background: #f5f7fa;
    color: #606266;
  }

  a {
    color: #409eff;
    text-decoration: none;
    &:hover { text-decoration: underline; }
  }
}
</style>
