class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/75/37/cd27d1747b3bb5050caa0593fd83521fc575f76f6bc09172e09e2d098db8/agentops_mcp_server-0.1.2.tar.gz"
  sha256 "b3cdc3e941353c18b0f7dd5a5eea4dfebffce4938e9d56bb95d2e7a5c09dcd36"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
