class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/cc/e0/77e1f1c6d5bd86887f9cf9285c1a8b0816a29678db5a13b98d14e5670068/agentops_mcp_server-0.0.1.tar.gz"
  sha256 "66efd71ee14864400578cb86bbeb7814ddd3b34d9d0f6b96b56e4c0d4853ab81"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
