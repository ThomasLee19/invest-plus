declare namespace API {
  type Repository = {
    created_at: string
    file_name: string
    updated_at: string
    user_id: string
    chunk_method: string
    status: string
    session_id: string | null
  }

  type OfficialExample = {
    file_name: string
    updated_at: string
    chunk_method: string
    status: string
  }
}
