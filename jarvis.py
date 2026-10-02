if sc.turn_complete:
                        speak_jarvis(" ".join(out_buf))
                        if self._turn_done_event:
                            self._turn_done_event.set()
                        self._reply_started = False
                        if self._suppress_reply:
                            self._suppress_reply = False
                        full_in_q = " ".join(in_buf).strip()
                        if full_in_q:
                            self.ui.write_log(f"You: {full_in_q}")
                            self._session_log.append(f"User: {full_in_q}")
                        in_buf, out_buf = [], []
                        self._visemes.reset()
                        continue