// Two screens, chosen by whether anyone is signed in. There is no router:
// with a login page and a chat page, a router would be more configuration than
// the two lines it replaces.

import { useAuth } from './context/AuthContext'
import { LoginPage } from './pages/LoginPage'
import { ChatPage } from './pages/ChatPage'

export default function App() {
  const { user, restoring } = useAuth()

  if (restoring) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-accent" />
      </div>
    )
  }

  return user ? <ChatPage /> : <LoginPage />
}
