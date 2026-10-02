export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.18"
  }
  public: {
    Tables: {
      assistant_settings: {
        Row: {
          assistant_name: string
          avatar_id: string
          language: string
          updated_at: string
          user_id: string
          voice: string | null
        }
        Insert: {
          assistant_name?: string
          avatar_id?: string
          language?: string
          updated_at?: string
          user_id: string
          voice?: string | null
        }
        Update: {
          assistant_name?: string
          avatar_id?: string
          language?: string
          updated_at?: string
          user_id?: string
          voice?: string | null
        }
        Relationships: []
      }
      audit_events: {
        Row: {
          action: string
          actor: string
          created_at: string
          hash: string | null
          id: number
          payload: Json | null
          prev_hash: string | null
          session_id: string | null
          user_id: string | null
        }
        Insert: {
          action: string
          actor: string
          created_at?: string
          hash?: string | null
          id?: number
          payload?: Json | null
          prev_hash?: string | null
          session_id?: string | null
          user_id?: string | null
        }
        Update: {
          action?: string
          actor?: string
          created_at?: string
          hash?: string | null
          id?: number
          payload?: Json | null
          prev_hash?: string | null
          session_id?: string | null
          user_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "audit_events_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      consents: {
        Row: {
          created_at: string
          explanation_version: string
          granted: boolean
          id: string
          scope: string
          user_id: string
        }
        Insert: {
          created_at?: string
          explanation_version: string
          granted: boolean
          id?: string
          scope: string
          user_id: string
        }
        Update: {
          created_at?: string
          explanation_version?: string
          granted?: boolean
          id?: string
          scope?: string
          user_id?: string
        }
        Relationships: []
      }
      documents: {
        Row: {
          created_at: string
          doc_type: string | null
          error: string | null
          id: string
          mime: string | null
          ocr: Json | null
          page_count: number | null
          quality: Json | null
          session_id: string
          sha256: string | null
          status: string
          storage_path: string
          user_id: string
        }
        Insert: {
          created_at?: string
          doc_type?: string | null
          error?: string | null
          id?: string
          mime?: string | null
          ocr?: Json | null
          page_count?: number | null
          quality?: Json | null
          session_id: string
          sha256?: string | null
          status?: string
          storage_path: string
          user_id: string
        }
        Update: {
          created_at?: string
          doc_type?: string | null
          error?: string | null
          id?: string
          mime?: string | null
          ocr?: Json | null
          page_count?: number | null
          quality?: Json | null
          session_id?: string
          sha256?: string | null
          status?: string
          storage_path?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "documents_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      fetched_content: {
        Row: {
          fetched_at: string
          id: string
          session_id: string
          text: string
          title: string | null
          url: string
          user_id: string
        }
        Insert: {
          fetched_at?: string
          id?: string
          session_id: string
          text: string
          title?: string | null
          url: string
          user_id: string
        }
        Update: {
          fetched_at?: string
          id?: string
          session_id?: string
          text?: string
          title?: string | null
          url?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "fetched_content_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      field_values: {
        Row: {
          confidence: number | null
          created_at: string
          field_key: string
          id: string
          resolution_reason: string | null
          resolves_flag_id: string | null
          session_id: string
          source_ref: Json
          source_type: string
          status: string
          user_id: string
          value: string | null
          value_normalized: string | null
        }
        Insert: {
          confidence?: number | null
          created_at?: string
          field_key: string
          id?: string
          resolution_reason?: string | null
          resolves_flag_id?: string | null
          session_id: string
          source_ref?: Json
          source_type: string
          status?: string
          user_id: string
          value?: string | null
          value_normalized?: string | null
        }
        Update: {
          confidence?: number | null
          created_at?: string
          field_key?: string
          id?: string
          resolution_reason?: string | null
          resolves_flag_id?: string | null
          session_id?: string
          source_ref?: Json
          source_type?: string
          status?: string
          user_id?: string
          value?: string | null
          value_normalized?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "field_values_resolves_flag_id_fkey"
            columns: ["resolves_flag_id"]
            isOneToOne: false
            referencedRelation: "flags"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "field_values_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      flags: {
        Row: {
          created_at: string
          details: Json
          field_key: string | null
          id: string
          reason_code: string
          resolution: Json | null
          resolved_at: string | null
          session_id: string
          severity: string
          status: string
          type: string
          user_id: string
        }
        Insert: {
          created_at?: string
          details?: Json
          field_key?: string | null
          id?: string
          reason_code: string
          resolution?: Json | null
          resolved_at?: string | null
          session_id: string
          severity: string
          status?: string
          type: string
          user_id: string
        }
        Update: {
          created_at?: string
          details?: Json
          field_key?: string | null
          id?: string
          reason_code?: string
          resolution?: Json | null
          resolved_at?: string | null
          session_id?: string
          severity?: string
          status?: string
          type?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "flags_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      form_sessions: {
        Row: {
          created_at: string
          id: string
          phase: string
          portal: string | null
          portal_url: string | null
          scheme_key: string | null
          status: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          phase?: string
          portal?: string | null
          portal_url?: string | null
          scheme_key?: string | null
          status?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          phase?: string
          portal?: string | null
          portal_url?: string | null
          scheme_key?: string | null
          status?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      gpu_endpoints: {
        Row: {
          last_seen: string | null
          models: Json | null
          name: string
          url: string
        }
        Insert: {
          last_seen?: string | null
          models?: Json | null
          name: string
          url: string
        }
        Update: {
          last_seen?: string | null
          models?: Json | null
          name?: string
          url?: string
        }
        Relationships: []
      }
      gpu_secrets: {
        Row: {
          id: number
          secret: string
        }
        Insert: {
          id?: number
          secret: string
        }
        Update: {
          id?: number
          secret?: string
        }
        Relationships: []
      }
      messages: {
        Row: {
          content: string | null
          created_at: string
          id: string
          input_mode: string | null
          lang: string | null
          provider: string | null
          role: string
          session_id: string
          tool_name: string | null
          tool_payload: Json | null
          user_id: string
        }
        Insert: {
          content?: string | null
          created_at?: string
          id?: string
          input_mode?: string | null
          lang?: string | null
          provider?: string | null
          role: string
          session_id: string
          tool_name?: string | null
          tool_payload?: Json | null
          user_id: string
        }
        Update: {
          content?: string | null
          created_at?: string
          id?: string
          input_mode?: string | null
          lang?: string | null
          provider?: string | null
          role?: string
          session_id?: string
          tool_name?: string | null
          tool_payload?: Json | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "messages_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      profile_field_sources: {
        Row: {
          confirmed_at: string
          field_key: string
          source_ref: Json
          source_type: string
          user_id: string
        }
        Insert: {
          confirmed_at?: string
          field_key: string
          source_ref?: Json
          source_type: string
          user_id: string
        }
        Update: {
          confirmed_at?: string
          field_key?: string
          source_ref?: Json
          source_type?: string
          user_id?: string
        }
        Relationships: []
      }
      profile_proposals: {
        Row: {
          created_at: string
          evidence: string
          id: string
          message_id: string | null
          session_id: string | null
          status: string
          updates: Json
          user_id: string
        }
        Insert: {
          created_at?: string
          evidence: string
          id?: string
          message_id?: string | null
          session_id?: string | null
          status?: string
          updates: Json
          user_id: string
        }
        Update: {
          created_at?: string
          evidence?: string
          id?: string
          message_id?: string | null
          session_id?: string | null
          status?: string
          updates?: Json
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "profile_proposals_message_id_fkey"
            columns: ["message_id"]
            isOneToOne: false
            referencedRelation: "messages"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "profile_proposals_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          aadhaar_last4: string | null
          annual_family_income: number | null
          caste: string | null
          category: string | null
          created_at: string
          current_course: string | null
          current_year: number | null
          district: string | null
          dob: string | null
          domicile_state: string | null
          email: string | null
          full_name: string | null
          full_name_local: string | null
          gender: string | null
          hsc_board: string | null
          hsc_percentage: number | null
          hsc_year: number | null
          id: string
          institute_name: string | null
          mobile: string | null
          preferred_language: string
          religion: string | null
          ssc_board: string | null
          ssc_percentage: number | null
          ssc_year: number | null
          taluka: string | null
          updated_at: string
        }
        Insert: {
          aadhaar_last4?: string | null
          annual_family_income?: number | null
          caste?: string | null
          category?: string | null
          created_at?: string
          current_course?: string | null
          current_year?: number | null
          district?: string | null
          dob?: string | null
          domicile_state?: string | null
          email?: string | null
          full_name?: string | null
          full_name_local?: string | null
          gender?: string | null
          hsc_board?: string | null
          hsc_percentage?: number | null
          hsc_year?: number | null
          id: string
          institute_name?: string | null
          mobile?: string | null
          preferred_language?: string
          religion?: string | null
          ssc_board?: string | null
          ssc_percentage?: number | null
          ssc_year?: number | null
          taluka?: string | null
          updated_at?: string
        }
        Update: {
          aadhaar_last4?: string | null
          annual_family_income?: number | null
          caste?: string | null
          category?: string | null
          created_at?: string
          current_course?: string | null
          current_year?: number | null
          district?: string | null
          dob?: string | null
          domicile_state?: string | null
          email?: string | null
          full_name?: string | null
          full_name_local?: string | null
          gender?: string | null
          hsc_board?: string | null
          hsc_percentage?: number | null
          hsc_year?: number | null
          id?: string
          institute_name?: string | null
          mobile?: string | null
          preferred_language?: string
          religion?: string | null
          ssc_board?: string | null
          ssc_percentage?: number | null
          ssc_year?: number | null
          taluka?: string | null
          updated_at?: string
        }
        Relationships: []
      }
      public_endpoints: {
        Row: {
          last_seen: string | null
          name: string
          url: string
        }
        Insert: {
          last_seen?: string | null
          name: string
          url: string
        }
        Update: {
          last_seen?: string | null
          name?: string
          url?: string
        }
        Relationships: []
      }
      research_results: {
        Row: {
          created_at: string
          id: string
          items: Json
          kind: string
          origin: string
          session_id: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          items: Json
          kind: string
          origin: string
          session_id: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          items?: Json
          kind?: string
          origin?: string
          session_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "research_results_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      rule_evaluations: {
        Row: {
          created_at: string
          id: string
          inputs: Json
          result: boolean
          rule_id: string
          rule_version: string
          session_id: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          inputs: Json
          result: boolean
          rule_id: string
          rule_version: string
          session_id: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          inputs?: Json
          result?: boolean
          rule_id?: string
          rule_version?: string
          session_id?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "rule_evaluations_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "form_sessions"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      register_gpu: {
        Args: {
          p_models: Json
          p_name: string
          p_secret: string
          p_url: string
        }
        Returns: undefined
      }
      register_public_endpoint: {
        Args: { p_name: string; p_secret: string; p_url: string }
        Returns: undefined
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends (DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never) = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends (DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never) = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends (PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never) = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
