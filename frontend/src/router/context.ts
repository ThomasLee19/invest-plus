import { createContext } from 'react'
import { createBrowserRouter } from 'react-router-dom'

type Router = ReturnType<typeof createBrowserRouter>

export const RouterContext = createContext<Router>(null as unknown as Router)
