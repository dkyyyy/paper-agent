<script setup lang="ts">
import ChatPanel from '../components/ChatPanel/ChatPanel.vue'
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>Paper Agent</h2>
      </div>
      <div class="sidebar-content">
        <!-- SessionList 组件在任务 7.6 中实现 -->
        <p class="placeholder">会话列表开发中</p>
      </div>
    </div>
    <div class="main">
      <ChatPanel />
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat-view {
  display: flex;
  height: 100vh;
}

.sidebar {
  width: 280px;
  border-right: 1px solid #e4e7ed;
  background: #fff;
  display: flex;
  flex-direction: column;

  .sidebar-header {
    padding: 16px;
    border-bottom: 1px solid #e4e7ed;

    h2 {
      font-size: 18px;
      color: #303133;
    }
  }

  .sidebar-content {
    flex: 1;
    overflow-y: auto;
  }

  .placeholder {
    padding: 20px;
    color: #c0c4cc;
    text-align: center;
    font-size: 13px;
  }
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
</style>
