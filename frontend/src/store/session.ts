import { proxy } from 'valtio'

const state = proxy({
  useDeep: true,
})

const actions = {
  setUseDeep(useDeep: boolean) {
    state.useDeep = useDeep
  },
}

export const sessionState = state
export const sessionActions = actions
