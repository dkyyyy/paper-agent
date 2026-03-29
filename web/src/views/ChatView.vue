<script setup lang="ts">
import ChatPanel from '../components/ChatPanel/ChatPanel.vue'
import SessionList from '../components/Sidebar/SessionList.vue'

function handleSwitchSession(_sessionId: string) {
  // Reconnect WebSocket with new session
  // ChatPanel handles this internally via useStreaming
}
</script>

<template>
  <div class="chat-view">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>📄 Paper Agent</h2>
      </div>
      <SessionList
        @switch-session="handleSwitchSession"
      />
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
