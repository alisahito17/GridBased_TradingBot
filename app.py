import streamlit as st
import json
import os
import time
from logic import start_bot, stop_bot, running_bots, get_bot_logs
 
# Bot storage file
BOTS_FILE = "bots.json"

def load_bots():
    if os.path.exists(BOTS_FILE):
        try:
            with open(BOTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_bots(bots):
    with open(BOTS_FILE, 'w') as f:
        json.dump(bots, f, indent=4)

# Initialize session state
if 'bots' not in st.session_state:
    st.session_state.bots = load_bots()

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Dashboard", "Create Bot"])

# Dashboard Page
if page == "Dashboard":
    st.title("🚀 Bots Dashboard")
    
    if st.button("➕ Create New Bot"):
        st.session_state.current_page = "Create Bot"
        st.rerun()
    
    st.divider()
    
    bots = st.session_state.bots
    if not bots:
        st.info("No bots created yet. Click 'Create New Bot' to get started.")
    else:
        for bot_name, bot_config in bots.items():
            with st.expander(f"🤖 {bot_name}", expanded=False):
                # Display config
                st.caption(f"🔑 {bot_config['wallet_address'][:6]}...{bot_config['wallet_address'][-4:]}")
                st.write(f"**Token:** {bot_config['token_symbol']}")
                st.write(f"**Price Range:** ${bot_config['min_price']} - ${bot_config['max_price']}")
                st.write(f"**Bin Step:** {bot_config['bin_step']} | **Order Size:** {bot_config['order_size']}")
                
                # Status and controls
                col1, col2 = st.columns([1,1])
                with col1:
                    if bot_name in running_bots:
                        st.success("🟢 RUNNING")
                    else:
                        st.warning("🔴 STOPPED")
                
                with col2:
                    if bot_name in running_bots:
                        if st.button("⏹️ Stop", key=f"stop_{bot_name}"):
                            stop_bot(bot_name)
                            st.success(f"Stopped {bot_name}")
                            time.sleep(1)
                            st.rerun()
                    else:
                        if st.button("▶️ Start", key=f"start_{bot_name}"):
                            try:
                                success = start_bot(bot_name, bot_config)
                                if success:
                                    st.success(f"Started {bot_name}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"❌ Bot {bot_name} did not start. `start_bot()` returned False.")
                            except Exception as e:
                                st.error(f"❌ Start failed due to error: {e}")
                                st.stop()

                
                # Edit and delete buttons
                col3, col4 = st.columns([1,1])
                with col3:
                    if st.button("✏️ Edit", key=f"edit_{bot_name}"):
                        st.session_state.edit_bot = bot_name
                        st.session_state.current_page = "Create Bot"
                        st.rerun()
                with col4:
                    if st.button("🗑️ Delete", key=f"delete_{bot_name}"):
                        if bot_name in running_bots:
                            stop_bot(bot_name)
                        del bots[bot_name]
                        save_bots(bots)
                        st.session_state.bots = bots
                        st.success(f"Deleted {bot_name}")
                        time.sleep(1)
                        st.rerun()
                
                # Live logs
                if bot_name in running_bots:
                    st.subheader("Live Logs")
                    logs = get_bot_logs(bot_name)
                    if logs:
                        log_text = "\n".join(logs[-10:])  # Show last 10 logs
                        st.text_area("", value=log_text, height=150, key=f"logs_{bot_name}")
                    else:
                        st.info("No logs yet")

# Create Bot Page
elif page == "Create Bot":
    st.title("🛠️ Create a New Trading Bot")
    
    edit_mode = 'edit_bot' in st.session_state
    if edit_mode:
        bot_name = st.session_state.edit_bot
        bot_config = st.session_state.bots[bot_name]
        st.info(f"Editing bot: {bot_name}")
    else:
        bot_config = {}
    
    with st.form(key='bot_form'):
        bot_name = st.text_input("Bot Name*", value=bot_config.get('bot_name', ''))
        token_symbol = st.text_input("Token Symbol*", value=bot_config.get('token_symbol', '')).upper()
        wallet_address = st.text_input("Wallet Address*", value=bot_config.get('wallet_address', ''))
        private_key = st.text_input("Private Key*", type="password", value=bot_config.get('private_key', ''))
        
        col1, col2 = st.columns(2)
        with col1:
            # Set default to 0.0001 to avoid min_value error
            min_price = st.number_input("Minimum Price*", min_value=0.0001, step=0.0001, 
                                       format="%.4f", value=bot_config.get('min_price', 0.0001))
        with col2:
            # Set default to 0.0001 to avoid min_value error
            max_price = st.number_input("Maximum Price*", min_value=0.0001, step=0.0001, 
                                       format="%.4f", value=bot_config.get('max_price', 0.0001))
        
        # Set defaults to 0.0001 to avoid min_value error
        bin_step = st.number_input("Bin Step*", min_value=0.0001, step=0.0001, 
                                  format="%.4f", value=bot_config.get('bin_step', 0.0001))
        order_size = st.number_input("Order Size*", min_value=0.0001, step=0.0001, 
                                    format="%.4f", value=bot_config.get('order_size', 0.0001))
        
        # Fixed: Use st.form_submit_button correctly
        submitted = st.form_submit_button("💾 Save Bot")
        
        if submitted:
            if not bot_name or not token_symbol or not wallet_address or not private_key:
                st.error("Please fill all required fields (*)")
            elif min_price >= max_price:
                st.error("Maximum price must be greater than minimum price")
            else:
                new_bot = {
                    'bot_name': bot_name,
                    'token_symbol': token_symbol,
                    'wallet_address': wallet_address,
                    'private_key': private_key,
                    'min_price': min_price,
                    'max_price': max_price,
                    'bin_step': bin_step,
                    'order_size': order_size
                }
                
                bots = st.session_state.bots
                if edit_mode:
                    # Remove old bot if name changed
                    old_name = st.session_state.edit_bot
                    if old_name != bot_name and old_name in bots:
                        del bots[old_name]
                
                bots[bot_name] = new_bot
                save_bots(bots)
                st.session_state.bots = bots
                
                st.success(f"✅ Bot '{bot_name}' saved successfully!")
                time.sleep(1)
                if 'edit_bot' in st.session_state:
                    del st.session_state.edit_bot
                st.session_state.current_page = "Dashboard"
                st.rerun()

# Footer
st.sidebar.divider()
st.sidebar.caption("HyperLiquid Grid Bot v1.0")